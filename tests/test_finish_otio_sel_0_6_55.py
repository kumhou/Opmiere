"""finish_selection_delivery + export_selection_otio_default (0.6.55)."""

from __future__ import annotations

import json
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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_finish_and_otio_default():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fo_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        otio = ed.export_selection_otio_default(
            [c.id], filename="sel.otio.json", title="t55",
        )
        p = Path(otio.get("path") or "")
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("OTIO_SCHEMA") == "Timeline.1"
        assert int(otio.get("clip_count") or 0) >= 1

        fin = ed.finish_selection_delivery(
            [c.id],
            filename="sel_finish.mp4",
            prepare=True,
            run_review=True,
            write_manifest=True,
            normalize_preset=None,
            delivery_preset="streaming",
        )
        assert "steps" in fin
        assert "delivery_check_selection" in (fin.get("steps") or [])
        ep = Path(fin.get("export_path") or "")
        assert ep.is_file() or (
            ed.bundle.root / "exports" / "sel_finish.mp4"
        ).is_file()
        man = ed.bundle.root / "exports" / "selection_finish_manifest.json"
        assert man.is_file() or fin.get("manifest")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_55():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/finish_selection_delivery" in app
    assert "/api/edit/export_selection_otio_default" in app
    assert "def finish_selection_delivery" in mcp
    assert "def export_selection_otio_default" in mcp
    assert 'id="btn-finish-sel"' in html
    assert 'id="btn-otio-sel"' in html
    assert "finishSelectionDeliveryUi" in ts
    assert "exportSelectionOtioDefaultUi" in ts
