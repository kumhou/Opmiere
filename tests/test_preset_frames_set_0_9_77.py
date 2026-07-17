"""export_selection_set_with_preset + export_selection_set_frame_sequence (0.9.77)."""

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


def test_preset_and_frame_sequence_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_prfr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        exp = ed.export_selection_set_with_preset(
            "hero",
            preset="draft",
            prepare=False,
        )
        assert exp.get("selection_set") == "hero"
        assert exp.get("preset") == "draft"
        path = exp.get("path") or exp.get("output_path")
        assert path and Path(str(path)).is_file()

        frames = ed.export_selection_set_frame_sequence(
            "hero",
            max_frames=3,
            pattern="frame_%06d.png",
        )
        assert frames.get("selection_set") == "hero"
        out = frames.get("out_dir") or frames.get("path") or frames.get("directory")
        assert out
        out_p = Path(str(out))
        if out_p.is_dir():
            pngs = list(out_p.glob("*.png"))
            assert len(pngs) >= 1
        else:
            assert out_p.exists() or any(
                Path(str(frames.get(k))).exists()
                for k in ("first_frame", "sample_path")
                if frames.get(k)
            )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_77():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_set_with_preset" in app
    assert "/api/edit/export_selection_set_frame_sequence" in app
    assert "def export_selection_set_with_preset" in mcp
    assert "def export_selection_set_frame_sequence" in mcp
    assert 'id="btn-exp-preset-set"' in html
    assert 'id="btn-exp-frames-set"' in html
    assert "exportSelectionSetWithPresetUi" in ts
    assert "exportSelectionSetFrameSequenceUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "export_selection_set_with_preset" in cat["tool_ids"]
    assert "export_selection_set_frame_sequence" in cat["tool_ids"]
