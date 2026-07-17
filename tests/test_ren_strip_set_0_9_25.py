"""rename_selection_set_from_media + strip_selection_set_path_c_unmapped (0.9.25)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_rename_from_media_and_strip_path_c():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rss_"))
    try:
        v = root / "clip_alpha.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        ren = ed.rename_selection_set_from_media("hero", suffix_index=False)
        assert ren.get("selection_set") == "hero"
        assert ren.get("count", 0) >= 1
        meta = ed.selection_set_meta_report("hero")
        names = [
            row.get("name")
            for row in (meta.get("clips") or [])
            if isinstance(row, dict)
        ]
        assert any(n and "clip_alpha" in str(n) for n in names)

        strip = ed.strip_selection_set_path_c_unmapped("hero")
        assert strip.get("selection_set") == "hero"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_25():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/rename_selection_set_from_media" in app
    assert "/api/edit/strip_selection_set_path_c_unmapped" in app
    assert "def rename_selection_set_from_media" in mcp
    assert "def strip_selection_set_path_c_unmapped" in mcp
    assert 'id="btn-ren-media-set"' in html
    assert 'id="btn-strip-pc-set"' in html
    assert "renameSelectionSetFromMediaUi" in ts
    assert "stripSelectionSetPathCUnmappedUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "rename_selection_set_from_media" in cat["tool_ids"]
    assert "strip_selection_set_path_c_unmapped" in cat["tool_ids"]
