"""export_selection_set_audio + formats_pack (0.8.6)."""

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
            "-f", "lavfi", "-i", f"color=c=khaki:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=190:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_audio_and_formats_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_saf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        aud = ed.export_selection_set_audio("hero")
        assert aud.get("ok") is True
        apath = Path(aud.get("export_path") or aud.get("path") or "")
        assert apath.is_file()
        assert apath.suffix.lower() in (".wav", ".mp3", ".m4a", ".aac")

        pack = ed.export_selection_set_formats_pack(
            "hero",
            include_mp4=True,
            include_webm=False,
            include_gif=True,
            include_audio=True,
            gif_width=120,
            gif_fps=8,
            gif_max_duration_seconds=2,
            normalize_preset=None,
        )
        assert pack.get("selection_set") == "hero"
        assert pack.get("clip_count") == 1
        out = Path(pack.get("out_dir") or "")
        assert out.is_dir()
        assert pack.get("count", 0) >= 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_6():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_audio" in app
    assert "/api/edit/export_selection_set_formats_pack" in app
    assert "def export_selection_set_audio" in mcp
    assert "def export_selection_set_formats_pack" in mcp
    assert 'id="btn-set-audio"' in html
    assert 'id="btn-set-fmt-pack"' in html
    assert "exportSelectionSetAudioUi" in ts
    assert "exportSelectionSetFormatsPackUi" in ts
