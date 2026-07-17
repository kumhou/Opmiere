"""batch_validate_selection_sets + batch_repair_selection_sets (0.7.7)."""

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
            "-f", "lavfi", "-i", f"color=c=cyan:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=160:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_batch_validate_and_repair():
    root = Path(tempfile.mkdtemp(prefix="opmiere_bvr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)
        c2 = ed.place_from_file(v, "video", tr.id, 10, duration_frames=10)
        ed.save_selection_set("a", [c1.id])
        ed.save_selection_set("b", [c2.id])

        val = ed.batch_validate_selection_sets(["a", "b"])
        assert val.get("count") == 2
        assert val.get("ok_count") + val.get("fail_count") == 2
        assert all("selection_set" in r for r in val["results"])

        rep = ed.batch_repair_selection_sets(
            ["a", "b"],
            unlock=True,
            ensure_proxies=False,
            pack_gaps=False,
        )
        assert rep.get("count") == 2
        assert rep.get("ok_count") + rep.get("fail_count") == 2
        names = {r["selection_set"] for r in rep["results"]}
        assert names == {"a", "b"}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_7_7():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/batch_validate_selection_sets" in app
    assert "/api/edit/batch_repair_selection_sets" in app
    assert "def batch_validate_selection_sets" in mcp
    assert "def batch_repair_selection_sets" in mcp
    assert 'id="btn-batch-val-set"' in html
    assert 'id="btn-batch-rep-set"' in html
    assert "batchValidateSelectionSetsUi" in ts
    assert "batchRepairSelectionSetsUi" in ts
