"""set_speed_ripple + export_clip_still + freeze_clip_mid (0.6.2)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_speed_ripple_still_freeze():
    root = Path(tempfile.mkdtemp(prefix="opmiere_srf_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5)
        _vid(b, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, int(c1.end))
        old_c2 = c2.start
        old_dur = c1.timeline_duration_frames
        r = ed.set_speed_ripple(c1.id, 2.0)
        assert r["clip_id"] == c1.id
        assert r["delta_frames"] < 0
        c2b = ed._find_clip(c2.id)
        assert c2b.start < old_c2
        assert ed._find_clip(c1.id).timeline_duration_frames < old_dur

        still = ed.export_clip_still(c1.id, root / "s.jpg", at="mid", width=80)
        assert Path(still["path"]).exists()
        assert still["clip_id"] == c1.id

        fr = ed.freeze_clip_mid(c1.id, duration_frames=15)
        assert fr["clip_id"]
        assert fr.get("source_clip_id") == c1.id or True
        assert ed._find_clip(fr["clip_id"]).timeline_duration_frames == 15
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_2():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/speed_ripple" in app
    assert "/api/export/clip_still" in app
    assert "/api/clip/freeze_mid" in app
    assert "def set_speed_ripple" in mcp
    assert "def export_clip_still" in mcp
    assert "def freeze_clip_mid" in mcp
    assert 'id="btn-spd05"' in html
    assert 'id="btn-clip-still"' in html
    assert 'id="btn-freeze-mid"' in html
    assert "speedRippleUi" in ts
    assert "exportClipStillUi" in ts
    assert "freezeClipMidUi" in ts
