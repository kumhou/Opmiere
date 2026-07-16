"""export_review_package + apply_watermark_to_track (0.5.81)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_apply_watermark_to_track_and_review_package():
    root = Path(tempfile.mkdtemp(prefix="opmiere_review_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        ed.add_marker(frame=1, label="A")
        r = ed.apply_watermark_to_track(tr.id, "© Test")
        assert r["count"] == 2
        for c in tr.clips:
            assert any(e.get("type") == "watermark" for e in (c.effects or []))
        out = root / "review"
        pkg = ed.export_review_package(
            out,
            include_handoff=True,
            include_storyboard=True,
            include_social=False,
        )
        assert Path(pkg["path"]).is_dir()
        assert (out / "handoff").is_dir() or Path(pkg["parts"]["handoff"]["path"]).exists()
        assert (out / "review_package.json").is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_81():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/review_package" in app
    assert "/api/track/watermark" in app
    assert "def export_review_package" in mcp
    assert "def apply_watermark_to_track" in mcp
    assert 'id="btn-review-pkg"' in html
    assert "exportReviewPackageUi" in ts
