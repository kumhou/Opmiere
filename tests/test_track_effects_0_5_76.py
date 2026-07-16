"""apply_effects_to_track + clear_effects (0.5.76)."""

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


def test_apply_and_clear_effects_on_track():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fxtrk_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.35, "navy")
        _vid(b, 0.35, "maroon")
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        r = ed.apply_effects_to_track(
            tr.id,
            [{"type": "color", "brightness": 0.1, "contrast": 1.1, "saturation": 1.0}],
            replace_types=True,
        )
        assert r["count"] == 2
        assert "color" in r["types"]
        for c in tr.clips:
            assert any(e.get("type") == "color" for e in (c.effects or []))
        # re-apply should not stack
        ed.apply_effects_to_track(
            tr.id,
            [{"type": "color", "brightness": 0.05, "contrast": 1.0, "saturation": 1.0}],
            replace_types=True,
        )
        for c in tr.clips:
            colors = [e for e in (c.effects or []) if e.get("type") == "color"]
            assert len(colors) == 1
        clr = ed.clear_effects(track_id=tr.id)
        assert clr["count"] == 2
        for c in tr.clips:
            assert not (c.effects or [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_76():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/track/apply_effects" in app
    assert "/api/effects/clear" in app
    assert "def apply_effects_to_track" in mcp
    assert "def clear_effects" in mcp
    assert 'id="btn-fx-track"' in html
    assert "applyEffectsTrackUi" in ts
