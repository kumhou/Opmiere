"""isolate_selection + move_selection_to_track + selection gain/opacity (0.6.16)."""

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
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_isolate_move_gain_opacity():
    root = Path(tempfile.mkdtemp(prefix="opmiere_img_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        tr2 = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        iso = ed.isolate_selection([c1.id])
        assert c1.id in iso["unmuted"]
        assert ed._find_clip(c1.id).muted is False
        assert ed._find_clip(c2.id).muted is True

        ed.unmute_all_clips()
        mv = ed.move_selection_to_track([c2.id], tr2.id, preserve_starts=True)
        assert mv["count"] == 1
        tr2_ids = {c.id for c in ed.project.track_by_id(tr2.id).clips}
        assert c2.id in tr2_ids

        g = ed.set_selection_gain([c1.id], -6.0)
        assert g["count"] == 1
        assert any(
            e.get("type") == "gain" and float(e.get("db", 0)) == -6.0
            for e in (ed._find_clip(c1.id).effects or [])
        )
        o = ed.set_selection_opacity([c1.id], 0.5)
        assert o["count"] == 1
        assert any(
            e.get("type") == "opacity" and abs(float(e.get("amount", 1)) - 0.5) < 1e-6
            for e in (ed._find_clip(c1.id).effects or [])
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_16():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/isolate_selection" in app
    assert "/api/edit/move_selection_to_track" in app
    assert "/api/edit/selection_gain" in app
    assert "/api/edit/selection_opacity" in app
    assert "def isolate_selection" in mcp
    assert "def move_selection_to_track" in mcp
    assert "def set_selection_gain" in mcp
    assert "def set_selection_opacity" in mcp
    assert 'id="btn-iso-sel"' in html
    assert 'id="btn-gain-sel"' in html
    assert 'id="btn-opac-sel"' in html
    assert "isolateSelectionUi" in ts
    assert "selectionGainUi" in ts
    assert "selectionOpacityUi" in ts
