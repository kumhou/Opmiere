"""compression_selection_set + noise_reduction_selection_set (0.9.48)."""

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
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_compression_and_noise_reduction_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cnr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        comp = ed.compression_selection_set("hero", ratio=3.0, threshold_db=-20.0)
        assert comp.get("selection_set") == "hero"
        assert comp.get("ratio") == 3.0
        assert "count" in comp

        nr = ed.noise_reduction_selection_set("hero", amount=10.0)
        assert nr.get("selection_set") == "hero"
        assert nr.get("amount") == 10.0
        assert "count" in nr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_48():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/compression_selection_set" in app
    assert "/api/edit/noise_reduction_selection_set" in app
    assert "def compression_selection_set" in mcp
    assert "def noise_reduction_selection_set" in mcp
    assert 'id="btn-comp-set"' in html
    assert 'id="btn-nr-set"' in html
    assert "compressionSelectionSetUi" in ts
    assert "noiseReductionSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "compression_selection_set" in cat["tool_ids"]
    assert "noise_reduction_selection_set" in cat["tool_ids"]
