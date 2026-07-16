"""import_folder (0.5.71)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_import_folder_place():
    root = Path(tempfile.mkdtemp(prefix="opmiere_impdir_"))
    try:
        media = root / "media"
        media.mkdir()
        _vid(media / "a.mp4", 0.4, "navy")
        _vid(media / "b.mp4", 0.4, "maroon")
        (media / "readme.txt").write_text("skip", encoding="utf-8")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        r = ed.import_folder(media, place=True, rough_cut=False)
        assert r["count"] == 2
        assert r["error_count"] == 0
        assert len(ed.project.media) == 2
        assert len(ed.project.tracks[0].clips) == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_import_folder_rough_cut():
    root = Path(tempfile.mkdtemp(prefix="opmiere_impdir2_"))
    try:
        media = root / "media"
        media.mkdir()
        _vid(media / "a.mp4", 0.35, "teal")
        _vid(media / "b.mp4", 0.35, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        r = ed.import_folder(media, rough_cut=True)
        assert r["count"] == 2
        assert r.get("rough_cut")
        assert len(ed.project.tracks[0].clips) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_71():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/import/folder" in app
    assert "def import_folder" in mcp
    assert 'id="btn-imp-folder"' in html
    assert "importFolderUi" in ts
