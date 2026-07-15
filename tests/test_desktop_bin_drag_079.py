"""Desktop bin→timeline drag place wiring (0.4.39)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bin_drag_to_timeline_wiring():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "application/x-opmiere-media" in ts
    assert "wireLaneMediaDrop" in ts
    assert "placeMediaOnTrack" in ts
    assert "draggable = true" in ts
    css = (ROOT / "ui-desktop" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "drop-media" in css
    assert "dragging-bin" in css
