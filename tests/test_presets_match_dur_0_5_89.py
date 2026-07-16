"""export_presets_pack + match_clip_duration (0.5.89)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_match_clip_duration():
    root = Path(tempfile.mkdtemp(prefix="opmiere_mdur_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.6, "navy")
        _vid(b, 0.3, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        c2 = ed.place_from_file(b, "video", tr.id, c1.end)
        target = c1.timeline_duration_frames
        r = ed.match_clip_duration(c2.id, target_clip_id=c1.id)
        assert abs(c2.timeline_duration_frames - target) <= 1
        assert r.get("target_clip_id") == c1.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_presets_pack_draft_only():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ppack_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.3)
        ed = Editor.create(root / "p.opm", fps=10, width=160, height=90)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        out = root / "pack"
        r = ed.export_presets_pack(out, presets=["draft"], name_prefix="t")
        assert r["count"] == 1
        assert Path(r["written"][0]["path"]).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_89():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/presets_pack" in app
    assert "/api/clip/match_duration" in app
    assert "def export_presets_pack" in mcp
    assert "def match_clip_duration" in mcp
    assert 'id="btn-presets-pack"' in html
    assert "exportPresetsPackUi" in ts
