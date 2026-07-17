"""selection_set_to_work_area + work_area_to_selection_set (0.9.4)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=110:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_set_and_work_area_bridge():
    root = Path(tempfile.mkdtemp(prefix="opmiere_swa_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)
        c3 = ed.place_from_file(v, "video", tr.id, 20, duration_frames=10)
        ed.save_selection_set("mid", [c2.id])

        wa = ed.selection_set_to_work_area("mid")
        assert wa.get("ok") is True
        assert wa["work_area"]["ready"] is True
        assert wa["work_area"]["in_frame"] == 10
        assert wa["work_area"]["out_frame"] == 20

        # expand WA to cover c1+c2+c3 partially
        ed._in_point = 5
        ed._out_point = 25
        built = ed.work_area_to_selection_set(
            "from_wa", mode="overlap", kind="video", overwrite=True,
        )
        assert built.get("ok") is True
        assert set(built["clip_ids"]) == {c1.id, c2.id, c3.id}

        contained = ed.work_area_to_selection_set(
            "from_wa_in", mode="contained", kind="video", overwrite=True,
        )
        # only c2 fully inside [5,25)
        assert set(contained["clip_ids"]) == {c2.id}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_4():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_to_work_area" in app
    assert "/api/edit/work_area_to_selection_set" in app
    assert "def selection_set_to_work_area" in mcp
    assert "def work_area_to_selection_set" in mcp
    assert 'id="btn-set-to-wa"' in html
    assert 'id="btn-wa-to-set"' in html
    assert "selectionSetToWorkAreaUi" in ts
    assert "workAreaToSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_to_work_area" in cat["tool_ids"]
    assert "work_area_to_selection_set" in cat["tool_ids"]
