"""Wiring smoke for 0.4.69."""
from pathlib import Path

def test_ship_0_4_69():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'writeSrtFromMarkersUi' in ts and 'btn-srt' in html

