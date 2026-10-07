"""Commercial transitions expose eligible notes only for the current program."""

from uuid import uuid4

import pytest

from app.ambient.catalog import SCENES
from app.web import server
from tests.test_ambient_canvas import engine, presence
from tests.test_ambient_web import application
from tests.test_web import client


@pytest.mark.asyncio
async def test_video_commercials_reveal_notes_then_hold_them_for_the_film():
    canvas, _ = engine()
    await presence(canvas, "mom")
    await canvas.simulate(str(uuid4()), "scene", "park_chase")
    program = await canvas.snapshot()
    assert program["notes"] == []
    assert program["note_waiting"]
    playback_id = program["media"]["playback_id"]
    for _ in range(2):
        await canvas.playback(str(uuid4()), playback_id, "break")
        commercial = await canvas.snapshot()
        assert commercial["media"]["phase"] == "break"
        assert [note["recipient"] for note in commercial["notes"]] == ["mom"]
        await canvas.playback(str(uuid4()), playback_id, "program")
        resumed = await canvas.snapshot()
        assert resumed["media"]["playback_id"] == playback_id
        assert resumed["notes"] == []
        assert resumed["note_waiting"]


@pytest.mark.asyncio
async def test_guests_still_hide_personal_notes_during_an_ad():
    canvas, _ = engine()
    await presence(canvas, "mom")
    await canvas.simulate(str(uuid4()), "scene", "park_chase")
    playback_id = (await canvas.snapshot())["media"]["playback_id"]
    await canvas.playback(str(uuid4()), playback_id, "break")
    assert (await canvas.snapshot())["notes"]
    await presence(canvas, "guest")
    assert not (await canvas.snapshot())["notes"]


@pytest.mark.asyncio
async def test_old_player_can_neither_start_a_break_nor_restore_its_old_program(tmp_path):
    path = str(tmp_path / "canvas.sqlite3")
    canvas, _ = engine(path)
    await canvas.simulate(str(uuid4()), "scene", "park_chase")
    old_id = (await canvas.snapshot())["media"]["playback_id"]
    await canvas.simulate(str(uuid4()), "scene", "cooking")
    current = (await canvas.snapshot())["media"]
    requests = [(str(uuid4()), phase) for phase in ("break", "program")]
    for identifier, phase in requests:
        assert await canvas.playback(identifier, old_id, phase) == "ignored"
        assert (await canvas.snapshot())["media"] == current
    canvas.store.close()
    restarted, _ = engine(path)
    for identifier, phase in requests:
        assert await restarted.playback(identifier, old_id, phase) == "ignored"
    assert (await restarted.snapshot())["media"] == current


@pytest.mark.asyncio
async def test_player_endpoint_is_bound_to_the_selected_session_and_origin():
    async with client(application()) as http:
        selected = await http.post(
            "/api/canvas/simulate",
            json={"request_id": str(uuid4()), "kind": "scene", "value": "park_chase"},
        )
        playback_id = selected.json()["media"]["playback_id"]
        body = {"request_id": str(uuid4()), "playback_id": playback_id, "phase": "break"}
        response = await http.post("/api/canvas/playback", json=body)
        assert response.status_code == 200
        assert response.json()["media"]["phase"] == "break"
        assert (await http.post("/api/canvas/playback", json=body)).status_code == 200
        forbidden = await http.post(
            "/api/canvas/playback", json=body, headers={"Origin": "https://elsewhere.invalid"}
        )
        assert forbidden.status_code == 403
        injected = await http.post(
            "/api/canvas/playback", json={**body, "source": "trusted-firetv"}
        )
        assert injected.status_code == 400
        invalid = await http.post(
            "/api/canvas/playback", json={**body, "request_id": str(uuid4()), "phase": "pay"}
        )
        assert invalid.status_code == 400


@pytest.mark.asyncio
async def test_unfinished_exports_stay_unavailable_until_the_film_and_ads_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "STATIC_DIRECTORY", tmp_path)
    stream = SCENES["park_chase"]["stream"]
    async with client(application()) as http:
        result = (await http.get("/api/canvas")).json()
        assert result["programs"]["park_chase"]["available"] is False
        paths = [stream["src"], stream["poster"], stream["captions"]]
        paths += [ad["src"] for ad in stream["breaks"]]
        for index, asset in enumerate(paths):
            path = tmp_path / asset.removeprefix("/static/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture asset")
            result = (await http.get("/api/canvas")).json()
            assert result["programs"]["park_chase"]["available"] is (index == len(paths) - 1)


@pytest.mark.asyncio
async def test_media_transport_supports_byte_ranges_for_browser_playback(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "STATIC_DIRECTORY", tmp_path)
    media = tmp_path / "media"
    media.mkdir()
    content = bytes(range(256)) * 4
    (media / "transport-fixture.mp4").write_bytes(content)
    async with client(application()) as http:
        response = await http.get(
            "/static/media/transport-fixture.mp4", headers={"Range": "bytes=256-511"}
        )
        assert response.status_code == 206
        assert response.content == content[256:512]
        assert response.headers["content-range"] == "bytes 256-511/1024"
        assert response.headers["content-type"] == "video/mp4"
        outside = await http.get(
            "/static/media/transport-fixture.mp4", headers={"Range": "bytes=2048-4095"}
        )
        assert outside.status_code == 416
