"""Wiring for 0.4.86."""
from pathlib import Path

def test_ship_0_4_86():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'mediaContactSheetUi' in ts and 'btn-media-sheet' in html

