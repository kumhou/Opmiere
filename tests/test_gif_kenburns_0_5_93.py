"""export_gif + apply_ken_burns (0.5.93)."""

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


def _still(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=orange:s=160x90:d=0.1",
            "-frames:v", "1", str(path),
        ],
        check=True,
    )


def test_ken_burns_and_gif():
    root = Path(tempfile.mkdtemp(prefix="opmiere_kb_"))
    try:
        v = root / "v.mp4"
        img = root / "s.jpg"
        _vid(v, 0.5)
        _still(img)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        kb = ed.apply_ken_burns(c.id, zoom_end=1.2)
        assert kb["clip_id"] == c.id
        assert any(
            e.get("type") == "ken_burns" and float(e.get("zoom_end", 0)) == 1.2
            for e in (ed._find_clip(c.id).effects or [])
        )
        # image still + batch helper
        still_clip = ed.place_from_file(
            img, "image", tr.id, int(c.end), duration_frames=30,
        )
        assert still_clip.id
        batch = ed.apply_ken_burns_to_images(zoom_end=1.1)
        assert batch["count"] >= 1
        assert still_clip.id in batch["clip_ids"]

        gif_path = root / "out.gif"
        g = ed.export_gif(gif_path, start_seconds=0, end_seconds=0.3, fps=8, width=120)
        assert Path(g["path"]).exists()
        assert g["bytes"] > 0
        assert g["path"].endswith(".gif")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_93():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/gif" in app
    assert "/api/clip/ken_burns" in app
    assert "def export_gif" in mcp
    assert "def apply_ken_burns" in mcp
    assert 'id="btn-gif"' in html
    assert 'id="btn-kb"' in html
    assert "exportGifUi" in ts
    assert "kenBurnsUi" in ts
