"""path-C gain/audio plan + balance_clip_gains + export_track_stems."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor
from opmiere.render.openshot_map import (
    ADAPTER_VERSION,
    build_openshot_plan,
    clip_visual_props,
)


def _vid(path: Path, d: float = 0.8) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def _wav(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8",
            "-c:a", "pcm_s16le", str(path),
        ],
        check=True,
    )


def test_path_c_gain_and_audio_plan():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ga_"))
    try:
        v = root / "v.mp4"
        a = root / "a.wav"
        _vid(v)
        _wav(a)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tv = ed.add_track("video")
        ta = ed.add_track("audio")
        c = ed.place_from_file(v, "video", tv.id, 0)
        ed.place_from_file(a, "audio", ta.id, 0)
        ed.set_clip_gain(c.id, -6.0)
        vis = clip_visual_props(ed.project.tracks[0].clips[0])
        assert "gain" in vis["mapped_effects"]
        assert abs(vis["gain_db"] + 6.0) < 0.01
        plan = build_openshot_plan(
            ed.project, ed.bundle, height=180, include_audio=True,
        )
        assert int(plan.get("adapter_version") or 0) >= 16
        assert int(ADAPTER_VERSION) >= 16
        assert plan["clips"][0].get("gain_db") == -6.0
        assert plan.get("audio_count", 0) >= 1
        assert plan["audio"][0]["kind"] == "audio"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_balance_clip_gains():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bal_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, 30)
        ed.set_clip_gain(c1.id, -6.0)
        ed.set_clip_gain(c2.id, 0.0)
        r = ed.balance_clip_gains([c1.id, c2.id], target_db=0.0, relative=True)
        assert r["count"] == 2
        # average was -3; delta +3 → -3 and +3
        g1 = ed.get_clip_gain_db(c1.id)
        g2 = ed.get_clip_gain_db(c2.id)
        assert abs((g1 + g2) / 2.0) < 0.2
        assert abs(g2 - g1 - 6.0) < 0.2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_track_stems_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_st_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        t0 = ed.add_track("video")
        t1 = ed.add_track("video")
        ed.place_from_file(v, "video", t0.id, 0)
        ed.place_from_file(v, "video", t1.id, 0)
        out = root / "stems"

        def _fake_export(path, normalize_preset=None):
            p = Path(path)
            _vid(p)
            return p

        with mock.patch.object(ed, "export", side_effect=_fake_export):
            r = ed.export_track_stems(out, track_ids=[t0.id, t1.id])
        assert r["count"] == 2
        assert r["ok"] is True
        # mute restored
        assert t0.muted is False
        assert t1.muted is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_57():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/track_stems" in app
    assert "/api/clips/balance_gains" in app
    assert "def export_track_stems" in mcp
    assert "def balance_clip_gains" in mcp
    assert 'id="btn-track-stems"' in html
    assert 'id="btn-bal-gain"' in html
    assert "exportTrackStemsUi" in ts
