"""Wiring for 0.4.78."""
from pathlib import Path

def test_ship_0_4_78():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'loadTranscriptUi' in ts and 'captionClipUi' in ts
    assert 'btn-transcript' in html and 'btn-caption' in html

