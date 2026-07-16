"""Wiring smoke for 0.4.68."""
from pathlib import Path

def test_ship_0_4_68():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'invalidatePreviewUi' in ts and 'btn-px-inval' in html
    assert 'clearRecentUi' in ts and 'btn-recent-clr' in html

