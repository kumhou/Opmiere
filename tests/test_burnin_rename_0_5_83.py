"""export_with_burnins + rename_clips_sequential (0.5.83)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_rename_clips_sequential():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rename_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        r = ed.rename_clips_sequential(tr.id, pattern="Shot {n:03d}", start=1)
        assert r["count"] == 2
        names = [c.name for c in tr.clips_in_order()]
        assert names[0] == "Shot 001"
        assert names[1] == "Shot 002"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_with_burnins():
    root = Path(tempfile.mkdtemp(prefix="opmiere_burn_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.3)
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        out = root / "review.mp4"
        r = ed.export_with_burnins(
            out, timecode=True, safe_area=True, watermark="REVIEW",
        )
        assert Path(r["path"]).is_file()
        assert Path(r["path"]).stat().st_size > 500
        # timeline must not gain permanent burn-in FX
        assert not any(
            e.get("type") in ("timecode", "safe_area", "watermark")
            for c in tr.clips
            for e in (c.effects or [])
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_83():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/burnins" in app
    assert "/api/track/rename_clips" in app
    assert "def export_with_burnins" in mcp
    assert "def rename_clips_sequential" in mcp
    assert 'id="btn-burnin"' in html
    assert "exportBurninsUi" in ts
