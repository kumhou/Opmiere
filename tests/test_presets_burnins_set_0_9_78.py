"""export_selection_set_presets_pack + export_selection_set_with_burnins (0.9.78)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_presets_pack_and_burnins_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_prbn_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        pack = ed.export_selection_set_presets_pack(
            "hero",
            presets=["draft"],
            prepare=False,
        )
        assert pack.get("selection_set") == "hero"
        assert pack.get("count", 0) >= 1
        out_dir = pack.get("out_dir")
        assert out_dir and Path(str(out_dir)).is_dir()

        burn = ed.export_selection_set_with_burnins(
            "hero",
            timecode=True,
            safe_area=True,
            watermark="REVIEW",
        )
        assert burn.get("selection_set") == "hero"
        path = burn.get("path") or burn.get("output_path")
        assert path and Path(str(path)).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_78():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_presets_pack" in app
    assert "/api/edit/export_selection_set_with_burnins" in app
    assert "def export_selection_set_presets_pack" in mcp
    assert "def export_selection_set_with_burnins" in mcp
    assert 'id="btn-exp-presets-pack-set"' in html
    assert 'id="btn-exp-burnins-set"' in html
    assert "exportSelectionSetPresetsPackUi" in ts
    assert "exportSelectionSetWithBurninsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_presets_pack" in cat["tool_ids"]
    assert "export_selection_set_with_burnins" in cat["tool_ids"]
