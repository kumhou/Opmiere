"""export_selection_set_mp4 + finish_selection_set_delivery (0.8.4)."""

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
            "-f", "lavfi", "-i", f"color=c=indigo:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=220:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_mp4_and_finish_delivery():
    root = Path(tempfile.mkdtemp(prefix="opmiere_smd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        mp4 = ed.export_selection_set_mp4("hero", normalize_preset=None)
        assert mp4.get("ok") is True
        path = Path(mp4.get("export_path") or mp4.get("path") or "")
        assert path.is_file()
        assert path.stat().st_size > 500
        assert mp4.get("selection_set") == "hero"

        fin = ed.finish_selection_set_delivery(
            "hero",
            prepare=True,
            unlock_tracks=True,
            set_work_area=True,
            pack_gaps=False,
            run_review=True,
            write_manifest=True,
            normalize_preset=None,
        )
        assert fin.get("selection_set") == "hero"
        assert (fin.get("loaded") or {}).get("clip_count") == 1
        assert isinstance(fin.get("steps"), list)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_8_4():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_mp4" in app
    assert "/api/edit/finish_selection_set_delivery" in app
    assert "def export_selection_set_mp4" in mcp
    assert "def finish_selection_set_delivery" in mcp
    assert 'id="btn-set-mp4"' in html
    assert 'id="btn-set-deliv"' in html
    assert "exportSelectionSetMp4Ui" in ts
    assert "finishSelectionSetDeliveryUi" in ts
