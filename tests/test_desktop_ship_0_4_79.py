"""Wiring for 0.4.79."""
from pathlib import Path

def test_ship_0_4_79():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'exportRangeIoUi' in ts and 'previewRangeIoUi' in ts
    assert 'btn-exp-range' in html and 'btn-px-range' in html

