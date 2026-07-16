"""Wiring for 0.4.88."""
from pathlib import Path

def test_ship_0_4_88():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'roomToneSuggestUi' in ts and 'btn-rt-suggest' in html
    assert 'btn-rt-extract' in html and 'btn-rt-place' in html

