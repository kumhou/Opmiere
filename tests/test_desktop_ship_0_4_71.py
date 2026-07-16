"""Wiring for 0.4.71."""
from pathlib import Path

def test_ship_0_4_71():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'showLooksUi' in ts and 'btn-looks' in html
    assert 'showEncodeStatusUi' in ts and 'btn-enc' in html
    assert '/api/looks' in ts and '/api/encode_status' in ts

