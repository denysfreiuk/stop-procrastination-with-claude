"""Start the bot at login: Task Scheduler on Windows, launchd on macOS, systemd on Linux."""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

WINDOWS_TASK = "StopProcrastinationBot"
LAUNCHD_LABEL = "com.stop-procrastination.bot"
SYSTEMD_UNIT = "stop-procrastination-bot.service"
RESTART_SECONDS = 30
PRIVATE_MAC_FOLDERS = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents")


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def bot_command(uv: str, bot_dir: Path) -> list[str]:
    return [uv, "run", "--quiet", "--no-project", "--directory", str(bot_dir), "--python", "3.14", "python", "launch.py"]


def windows_python(uv: str) -> Path:
    """pythonw has no console window and, unlike `uv run`, is a single process to stop."""
    found = run([uv, "python", "find", "3.14", "--system"]).stdout.strip()
    return Path(found).with_name("pythonw.exe")


def windows_task_xml(pythonw: Path, bot_dir: Path, user: str) -> str:
    # By default Task Scheduler stops a task after 3 days and on battery power.
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Telegram-бот щоденника Stop Procrastination</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(pythonw))}</Command>
      <Arguments>launch.py</Arguments>
      <WorkingDirectory>{escape(str(bot_dir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def launchd_plist(command: list[str], bot_dir: Path) -> bytes:
    log = str(bot_dir / "data" / "launchd.log")
    return plistlib.dumps(
        {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": command,
            "WorkingDirectory": str(bot_dir),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": RESTART_SECONDS,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def systemd_unit(command: list[str], bot_dir: Path) -> str:
    return f"""[Unit]
Description=Stop Procrastination Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={shlex.join(command)}
WorkingDirectory={bot_dir}
Restart=always
RestartSec={RESTART_SECONDS}
# On a server the bot shares the machine with other services: it may never take much.
MemoryMax=300M
CPUQuota=50%

[Install]
WantedBy=default.target
"""


def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def systemd_path() -> Path:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "systemd" / "user" / SYSTEMD_UNIT


def launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def mac_private_folder(root: Path, home: Path | None = None) -> str | None:
    """launchd agents get no access to these folders without a Full Disk Access prompt."""
    home = home or Path.home()
    for folder in PRIVATE_MAC_FOLDERS:
        if root.is_relative_to(home / folder):
            return folder
    return None


def install(uv: str, bot_dir: Path) -> None:
    (bot_dir / "data").mkdir(exist_ok=True)
    if sys.platform == "win32":
        _install_windows(uv, bot_dir)
    elif sys.platform == "darwin":
        path = launchd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(launchd_plist(bot_command(uv, bot_dir), bot_dir))
        run(["launchctl", "bootout", f"{launchd_domain()}/{LAUNCHD_LABEL}"], check=False)
        run(["launchctl", "bootstrap", launchd_domain(), str(path)])
    else:
        path = systemd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(bot_command(uv, bot_dir), bot_dir), encoding="utf-8")
        run(["systemctl", "--user", "daemon-reload"])
        run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT])
        run(["systemctl", "--user", "restart", SYSTEMD_UNIT])


def _install_windows(uv: str, bot_dir: Path) -> None:
    pythonw = windows_python(uv)
    if not pythonw.is_file():
        raise RuntimeError(f"Не знайдено {pythonw}")
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ['USERNAME']}".lstrip("\\")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "task.xml"
        path.write_text(windows_task_xml(pythonw, bot_dir, user), encoding="utf-16")
        run(["schtasks", "/Create", "/TN", WINDOWS_TASK, "/XML", str(path), "/F"])
    run(["schtasks", "/End", "/TN", WINDOWS_TASK], check=False)
    run(["schtasks", "/Run", "/TN", WINDOWS_TASK])


def restart() -> bool:
    """Restart the bot after an update; False when autostart was never set up."""
    if sys.platform == "win32":
        if run(["schtasks", "/Query", "/TN", WINDOWS_TASK], check=False).returncode != 0:
            return False
        run(["schtasks", "/End", "/TN", WINDOWS_TASK], check=False)
        run(["schtasks", "/Run", "/TN", WINDOWS_TASK])
    elif sys.platform == "darwin":
        if not launchd_path().exists():
            return False
        run(["launchctl", "kickstart", "-k", f"{launchd_domain()}/{LAUNCHD_LABEL}"])
    else:
        if not systemd_path().exists():
            return False
        run(["systemctl", "--user", "restart", SYSTEMD_UNIT])
    return True


def uninstall() -> bool:
    """Stop the bot and remove autostart; False when there was nothing to remove."""
    if sys.platform == "win32":
        if run(["schtasks", "/Query", "/TN", WINDOWS_TASK], check=False).returncode != 0:
            return False
        run(["schtasks", "/End", "/TN", WINDOWS_TASK], check=False)
        run(["schtasks", "/Delete", "/TN", WINDOWS_TASK, "/F"])
        return True
    if sys.platform == "darwin":
        path = launchd_path()
        if not path.exists():
            return False
        run(["launchctl", "bootout", f"{launchd_domain()}/{LAUNCHD_LABEL}"], check=False)
        path.unlink()
        return True
    path = systemd_path()
    if not path.exists():
        return False
    run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], check=False)
    path.unlink()
    run(["systemctl", "--user", "daemon-reload"], check=False)
    return True
