"""export_selection_with_preset + export_selection_with_burnins (0.6.64)."""

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
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_selection_preset_and_burnins():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pb_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        # draft: no loudnorm / no delivery_check — fast
        pr = ed.export_selection_with_preset(
            [c.id], preset="draft", prepare=False, filename="sel_draft.mp4",
        )
        assert pr.get("preset") == "draft"
        p = Path(pr.get("path") or "")
        assert p.is_file() and p.stat().st_size > 500

        burn = ed.export_selection_with_burnins(
            [c.id],
            filename="sel_burn.mp4",
            timecode=True,
            safe_area=True,
            watermark="REVIEW",
        )
        bp = Path(burn.get("path") or "")
        assert bp.is_file() and bp.stat().st_size > 500
        assert burn.get("timecode") is True
        assert burn.get("safe_area") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_64():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_with_preset" in app
    assert "/api/edit/export_selection_with_burnins" in app
    assert "def export_selection_with_preset" in mcp
    assert "def export_selection_with_burnins" in mcp
    assert 'id="btn-preset-sel"' in html
    assert 'id="btn-burn-sel"' in html
    assert "exportSelectionWithPresetUi" in ts
    assert "exportSelectionWithBurninsUi" in ts
