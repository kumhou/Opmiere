"""export_work_area_gif_default + finish_work_area_delivery (0.6.59)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_wa_gif_and_finish():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wg_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.work_area_from_selection([c.id])

        gif = ed.export_work_area_gif_default(
            filename="wa.gif", fps=8, width=160, max_duration_seconds=5,
        )
        gp = Path(
            gif.get("path")
            or gif.get("output_path")
            or (ed.bundle.root / "exports" / "wa.gif")
        )
        assert gp.is_file() or (ed.bundle.root / "exports" / "wa.gif").is_file()

        fin = ed.finish_work_area_delivery(
            filename="wa_fin.mp4",
            prepare=True,
            run_review=True,
            normalize_preset=None,
            delivery_preset="streaming",
        )
        assert "steps" in fin
        assert any(
            "export_work_area" in s for s in (fin.get("steps") or [])
        )
        ep = Path(fin.get("export_path") or "")
        assert ep.is_file() or (
            ed.bundle.root / "exports" / "wa_fin.mp4"
        ).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_59():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_work_area_gif_default" in app
    assert "/api/edit/finish_work_area_delivery" in app
    assert "def export_work_area_gif_default" in mcp
    assert "def finish_work_area_delivery" in mcp
    assert 'id="btn-wa-gif-def"' in html
    assert 'id="btn-finish-wa"' in html
    assert "exportWorkAreaGifDefaultUi" in ts
    assert "finishWorkAreaDeliveryUi" in ts
