"""export_selection_presets_pack + finish_selection_social (0.6.65)."""

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
            "-f", "lavfi", "-i", f"color=c=purple:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=330:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_presets_pack_and_finish_social():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ps_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        pack = ed.export_selection_presets_pack(
            [c.id],
            presets=["draft"],
            prepare=False,
            name_prefix="sel",
        )
        assert int(pack.get("count") or 0) >= 1
        out_dir = Path(pack.get("out_dir") or "")
        assert out_dir.is_dir()
        written = pack.get("written") or []
        assert written
        p0 = Path(written[0].get("path") or "")
        assert p0.is_file() and p0.stat().st_size > 500

        # square is lighter than reels canvas; skip loudnorm for speed
        fin = ed.finish_selection_social(
            [c.id],
            variant="square",
            reframe=True,
            prepare=False,
            run_review=True,
            normalize_preset=None,
        )
        assert fin.get("variant") == "square"
        ep = Path(fin.get("export_path") or "")
        assert ep.is_file() and ep.stat().st_size > 500
        assert fin.get("ok") is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_65():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/export_selection_presets_pack" in app
    assert "/api/edit/finish_selection_social" in app
    assert "def export_selection_presets_pack" in mcp
    assert "def finish_selection_social" in mcp
    assert 'id="btn-preset-pack-sel"' in html
    assert 'id="btn-finish-social-sel"' in html
    assert "exportSelectionPresetsPackUi" in ts
    assert "finishSelectionSocialUi" in ts
