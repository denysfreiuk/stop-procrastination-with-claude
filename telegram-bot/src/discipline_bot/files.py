"""Safe file writes."""

from __future__ import annotations

import os
import time
from pathlib import Path

REPLACE_TRIES = 7


def atomic_write(path: Path, data: bytes) -> None:
    """Write through a temporary file, so a reader never sees half a note.

    The leading dot keeps Obsidian from indexing the temporary file. On Windows
    os.replace fails while another program has the target open, which lasts a moment.
    """
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.05 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)
