"""Wiring smoke for 0.4.70."""
from pathlib import Path

def test_ship_0_4_70():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert '/api/generate/status' in ts or 'generate/status' in ts
    assert 'btn-preflight' in html and 'btn-srt' in html
    assert 'btn-analyze-tl' in html and 'btn-fcpxml' in html

