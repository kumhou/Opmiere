"""Wiring for 0.4.90."""
from pathlib import Path

def test_ship_0_4_90():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'prepareForExportUi' in ts and 'btn-prep-exp2' in html
    assert 'btn-clip-gain-op' in html and 'btn-stems' in html

