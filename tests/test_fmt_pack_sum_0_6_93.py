"""selection_export_summary + export_selection_formats_pack (0.6.93)."""

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
            "-f", "lavfi", "-i", f"color=c=maroon:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=640:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_export_summary_and_formats_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        sm = ed.selection_export_summary([c.id])
        assert sm.get("validate_ok") is True
        assert int(sm.get("clip_count") or 0) == 1
        assert "suggested" in sm
        assert "tools" in sm

        # skip webm for speed in CI-like tests
        pack = ed.export_selection_formats_pack(
            [c.id],
            include_mp4=True,
            include_webm=False,
            include_gif=True,
            include_audio=True,
            gif_width=160,
            gif_fps=8,
            gif_max_duration_seconds=2.0,
            normalize_preset=None,
            name_prefix="t",
        )
        assert int(pack.get("count") or 0) >= 2
        assert pack.get("ok") is True
        out = Path(pack.get("out_dir") or "")
        assert out.is_dir()
        assert list(out.glob("*.mp4"))
        assert list(out.glob("*.gif")) or list(out.glob("*.wav"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_93():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_export_summary" in app
    assert "/api/edit/export_selection_formats_pack" in app
    assert "def selection_export_summary" in mcp
    assert "def export_selection_formats_pack" in mcp
    assert 'id="btn-exp-sum-sel"' in html
    assert 'id="btn-fmt-pack-sel"' in html
    assert "selectionExportSummaryUi" in ts
    assert "exportSelectionFormatsPackUi" in ts
