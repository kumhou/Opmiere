"""export_selection_set_webm + export_selection_set_gif (0.8.5)."""

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
            "-f", "lavfi", "-i", f"color=c=coral:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=200:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_set_webm_and_gif():
    root = Path(tempfile.mkdtemp(prefix="opmiere_swg_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        webm = ed.export_selection_set_webm("hero", crf=36, width=160)
        assert webm.get("ok") is True
        wpath = Path(webm.get("export_path") or webm.get("path") or "")
        assert wpath.is_file()
        assert wpath.suffix.lower() == ".webm"
        assert webm.get("selection_set") == "hero"

        gif = ed.export_selection_set_gif(
            "hero", fps=8, width=120, max_duration_seconds=2,
        )
        assert gif.get("ok") is True
        gpath = Path(gif.get("export_path") or gif.get("path") or "")
        assert gpath.is_file()
        assert gpath.suffix.lower() == ".gif"
        assert gif.get("clip_count") == 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_5():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_webm" in app
    assert "/api/edit/export_selection_set_gif" in app
    assert "def export_selection_set_webm" in mcp
    assert "def export_selection_set_gif" in mcp
    assert 'id="btn-set-webm"' in html
    assert 'id="btn-set-gif"' in html
    assert "exportSelectionSetWebmUi" in ts
    assert "exportSelectionSetGifUi" in ts
