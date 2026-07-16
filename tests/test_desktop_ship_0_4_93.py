"""Wiring for 0.4.93."""
from pathlib import Path

def test_ship_0_4_93():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'collectGenParams' in ts and 'gen-steps' in html
    assert 'gen-w' in html and 'gen-h' in html

