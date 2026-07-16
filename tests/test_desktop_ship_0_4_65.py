"""Wiring smoke for 0.4.65."""
from pathlib import Path

def test_ship_0_4_65():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'exportStillUi' in ts and 'btn-still' in html
    assert 'exportAudioUi' in ts and 'btn-audio-out' in html

