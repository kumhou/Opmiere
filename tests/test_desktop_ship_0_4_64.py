"""Wiring smoke for 0.4.64."""
from pathlib import Path

def test_ship_0_4_64():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'exportFcpxmlUi' in ts and 'btn-fcpxml' in html
    assert 'exportOtioUi' in ts and 'btn-otio' in html

