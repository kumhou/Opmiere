"""Wiring for 0.4.80."""
from pathlib import Path

def test_ship_0_4_80():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'offsetLinkedUi' in ts and 'analyzeAssetUi' in ts
    assert 'btn-off-link-m' in html and 'btn-asset-card' in html
    assert 'btn-looks' in html and 'btn-exp-range' in html

