"""export_selection_clips_gif_pack + export_selection_clips_webm_pack (0.6.78)."""

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
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=490:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_gif_and_webm_packs():
    root = Path(tempfile.mkdtemp(prefix="opmiere_gw_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        g = ed.export_selection_clips_gif_pack(
            [c.id],
            width=120,
            fps=8,
            max_duration_seconds=2.0,
            prefix="g",
        )
        assert int(g.get("count") or 0) >= 1
        assert g.get("ok") is True
        assert list(Path(g["output_dir"]).glob("*.gif"))

        w = ed.export_selection_clips_webm_pack(
            [c.id], crf=40, width=160, prefix="w",
        )
        assert int(w.get("count") or 0) >= 1
        assert w.get("ok") is True
        assert list(Path(w["output_dir"]).glob("*.webm"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_78():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_clips_gif_pack" in app
    assert "/api/edit/export_selection_clips_webm_pack" in app
    assert "def export_selection_clips_gif_pack" in mcp
    assert "def export_selection_clips_webm_pack" in mcp
    assert 'id="btn-gif-pack-sel"' in html
    assert 'id="btn-webm-pack-sel"' in html
    assert "exportSelectionClipsGifPackUi" in ts
    assert "exportSelectionClipsWebmPackUi" in ts
