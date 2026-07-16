"""Wiring for 0.5.33."""
from pathlib import Path

def test_ship_0_5_33():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    css = (root/'ui-desktop/src/styles.css').read_text(encoding='utf-8')
    assert 'track-lane.compact' in css

