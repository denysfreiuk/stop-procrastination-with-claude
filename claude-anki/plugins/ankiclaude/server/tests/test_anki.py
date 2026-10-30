from __future__ import annotations

import pytest

from anki_claude.errors import AnkiAuthError, AnkiNotRunningError, AnkiOutdatedError, SyncError

from .fake_ankiconnect import FakeAnkiConnect


async def test_connection_report_on_fresh_collection(fake: FakeAnkiConnect, make_anki) -> None:
    report = await make_anki(fake).connection_report()
    assert report["ok"] is True
    assert report["anki_connect"]["api_v1"] is True
    assert report["anki_connect"]["anki_version"] == "26.09.3"
    assert report["profile"] == "Користувач 1"
    assert report["root_deck"] == {"name": "Den", "exists": False, "subdecks": []}
    assert not any(report["note_types"].values())
    assert len(report["next_steps"]) == 2


async def test_connection_report_lists_existing_plugin_decks(make_anki) -> None:
    fake = FakeAnkiConnect(decks=["Типовий", "Den", "Den::ML", "Denmark"], models=["AC Vocab"])
    report = await make_anki(fake).connection_report()
    assert report["root_deck"] == {"name": "Den", "exists": True, "subdecks": ["Den::ML"]}
    assert report["note_types"]["AC Vocab"] is True


async def test_anki_not_running_gives_actionable_message(make_anki) -> None:
    with pytest.raises(AnkiNotRunningError) as info:
        await make_anki(FakeAnkiConnect(running=False)).connection_report()
    assert "Відкрий Anki" in str(info.value)
    assert "2055492159" in str(info.value)


async def test_wrong_api_key(make_anki) -> None:
    with pytest.raises(AnkiAuthError):
        await make_anki(FakeAnkiConnect(key="right"), ANKI_CONNECT_KEY="wrong").connection_report()


async def test_correct_api_key_reaches_both_apis(make_anki) -> None:
    fake = FakeAnkiConnect(key="right")
    report = await make_anki(fake, ANKI_CONNECT_KEY="right").connection_report()
    assert report["anki_connect"]["api_v1"] is True


async def test_too_old_ankiconnect(make_anki) -> None:
    with pytest.raises(AnkiOutdatedError):
        await make_anki(FakeAnkiConnect(api_version=5)).connection_report()


@pytest.mark.parametrize(
    ("fake", "source"),
    [
        (FakeAnkiConnect(reviewing=True), "api-v1"),
        (FakeAnkiConnect(reviewing=True, v1=False), "api-v6"),
        (FakeAnkiConnect(reviewing=True, v1=False, has_gui_review_active=False), "api-v6"),
    ],
)
async def test_review_status_with_every_api_generation(fake: FakeAnkiConnect, source: str, make_anki) -> None:
    anki = make_anki(fake)
    assert await anki.review_status() == {"reviewing": True, "side": "question" if source == "api-v1" else None, "source": source}
    fake.reviewing = False
    assert (await anki.review_status())["reviewing"] is False


async def test_sync_is_deferred_while_reviewing(make_anki) -> None:
    fake = FakeAnkiConnect(reviewing=True)
    result = await make_anki(fake).sync()
    assert result["status"] == "deferred"
    assert fake.syncs == 0


async def test_forced_sync_while_reviewing(make_anki) -> None:
    fake = FakeAnkiConnect(reviewing=True)
    result = await make_anki(fake).sync(force=True)
    assert result["status"] == "synced"
    assert fake.syncs == 1


async def test_sync_v1_waits_for_the_operation(make_anki) -> None:
    fake = FakeAnkiConnect(sync_states=["queued", "running", "running", "succeeded"])
    result = await make_anki(fake).sync()
    assert result["status"] == "synced"
    assert result["media"] is True
    assert fake.calls.count("operations.get") == 4


@pytest.mark.parametrize("v1", [True, False])
async def test_sync_without_ankiweb_login(v1: bool, make_anki) -> None:
    with pytest.raises(SyncError) as info:
        await make_anki(FakeAnkiConnect(v1=v1, logged_in=False)).sync()
    assert info.value.reason == "not_logged_in"
    assert "AnkiWeb" in str(info.value)


async def test_sync_needing_full_sync_reports_the_dialog(make_anki) -> None:
    with pytest.raises(SyncError) as info:
        await make_anki(FakeAnkiConnect(sync_states=["running", "waitingForUser"])).sync()
    assert info.value.reason == "full_sync_required"


async def test_sync_network_failure(make_anki) -> None:
    with pytest.raises(SyncError) as info:
        await make_anki(FakeAnkiConnect(sync_states=["running", "failed"])).sync()
    assert info.value.reason == "network"
    assert "інтернет" in str(info.value)


async def test_sync_v6_goes_through_multi_so_it_is_awaited(make_anki) -> None:
    fake = FakeAnkiConnect(v1=False)
    result = await make_anki(fake).sync()
    assert result["status"] == "synced"
    assert "multi" in fake.calls
    assert fake.syncs == 1
