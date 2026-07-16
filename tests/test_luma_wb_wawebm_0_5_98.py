"""apply_luma_key + apply_white_balance + export_work_area_webm (0.5.98)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.35) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_luma_wb_work_area_webm():
    root = Path(tempfile.mkdtemp(prefix="opmiere_lww_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        lk = ed.apply_luma_key(c.id, threshold=0.2, tolerance=0.15)
        assert lk["clip_id"] == c.id
        assert any(
            e.get("type") == "luma_key"
            for e in (ed._find_clip(c.id).effects or [])
        )
        wb = ed.apply_white_balance(c.id, temperature=5600, mix=0.8)
        assert wb["clip_id"] == c.id
        assert any(
            e.get("type") == "white_balance"
            and float(e.get("temperature", 0)) == 5600
            for e in (ed._find_clip(c.id).effects or [])
        )
        # strip FX for faster export
        with ed._mutate():
            ed._find_clip(c.id).effects = []
        ed.set_in_point(0)
        ed.set_out_point(8)
        out = ed.export_work_area_webm(root / "wa.webm", crf=40, width=100)
        assert Path(out["path"]).exists()
        assert out["path"].endswith(".webm")
        assert out["in_frame"] == 0
        assert out["out_frame"] == 8
        assert out["bytes"] > 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_98():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/luma_key" in app
    assert "/api/clip/white_balance" in app
    assert "/api/export/work_area_webm" in app
    assert "def apply_luma_key" in mcp
    assert "def apply_white_balance" in mcp
    assert "def export_work_area_webm" in mcp
    assert 'id="btn-lkey"' in html
    assert 'id="btn-wb"' in html
    assert 'id="btn-wa-webm"' in html
    assert "lumaKeyUi" in ts
    assert "whiteBalanceUi" in ts
    assert "exportWorkAreaWebmUi" in ts
