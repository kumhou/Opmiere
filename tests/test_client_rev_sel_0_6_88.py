"""finish_selection_review_export + export_selection_client_pack (0.6.88)."""

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
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=590:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_review_export_and_client_pack():
    root = Path(tempfile.mkdtemp(prefix="opmiere_cr_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        pack = ed.export_selection_client_pack(
            [c.id],
            include_card=True,
            include_stills=True,
            include_export=True,
            include_review_export=False,
            stills_width=160,
        )
        assert Path(pack.get("path") or "").is_dir()
        assert Path(pack.get("meta") or "").is_file()
        exp = pack.get("parts", {}).get("export") or {}
        if isinstance(exp, dict) and exp.get("path"):
            assert Path(exp["path"]).is_file()

        rev = ed.finish_selection_review_export(
            [c.id],
            filename="sel_rev.mp4",
            clear_overlays=True,
            normalize_preset=None,
        )
        assert rev.get("ok") is True
        ep = Path(rev.get("export_path") or "")
        assert ep.is_file() and ep.stat().st_size > 500
        # overlays cleared
        types = {
            e.get("type")
            for e in (ed._find_clip(c.id).effects or [])
            if isinstance(e, dict)
        }
        assert "watermark" not in types
        assert "safe_area" not in types
        assert "timecode" not in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_88():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/finish_selection_review_export" in app
    assert "/api/edit/export_selection_client_pack" in app
    assert "def finish_selection_review_export" in mcp
    assert "def export_selection_client_pack" in mcp
    assert 'id="btn-fin-rev-sel"' in html
    assert 'id="btn-client-pack-sel"' in html
    assert "finishSelectionReviewExportUi" in ts
    assert "exportSelectionClientPackUi" in ts
