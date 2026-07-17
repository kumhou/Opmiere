"""export_selection_handoff + export_selection_review_package (0.6.69)."""

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
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=400:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_selection_handoff_and_review():
    root = Path(tempfile.mkdtemp(prefix="opmiere_hr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.45)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.add_marker(frame=4, label="beat")

        ho = ed.export_selection_handoff([c.id], include_otio=False)
        assert Path(ho.get("path") or "").is_dir()
        assert (Path(ho["path"]) / "handoff.json").is_file()
        assert int(ho.get("count") or 0) >= 2

        rev = ed.export_selection_review_package(
            [c.id],
            include_handoff=True,
            include_storyboard=True,
            include_export=True,
            include_social=False,
            normalize_preset=None,
        )
        assert Path(rev.get("path") or "").is_dir()
        assert Path(rev.get("meta") or "").is_file()
        exp = rev.get("parts", {}).get("export") or {}
        if isinstance(exp, dict) and exp.get("path"):
            assert Path(exp["path"]).is_file()
        else:
            # export may key under nested path field from export_selection_mp4
            assert "export" in (rev.get("parts") or {})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_69():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_handoff" in app
    assert "/api/edit/export_selection_review_package" in app
    assert "def export_selection_handoff" in mcp
    assert "def export_selection_review_package" in mcp
    assert 'id="btn-handoff-sel"' in html
    assert 'id="btn-review-pack-sel"' in html
    assert "exportSelectionHandoffUi" in ts
    assert "exportSelectionReviewPackageUi" in ts
