"""Wiring for 0.4.81."""
from pathlib import Path

def test_ship_0_4_81():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'enrichClipGainOpacity' in ts and 'btn-clip-gain-op' in html
    assert 'trimClipToIoUi' in ts and 'btn-trim-src' in html

