"""Wiring for 0.4.89."""
from pathlib import Path

def test_ship_0_4_89():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'separateStemsUi' in ts and 'extractFrameBinUi' in ts
    assert 'btn-stems' in html and 'btn-frame-bin' in html

