"""Wiring for 0.4.82."""
from pathlib import Path

def test_ship_0_4_82():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'slugMediaUi' in ts and 'btn-slug' in html and 'btn-slug-place' in html

