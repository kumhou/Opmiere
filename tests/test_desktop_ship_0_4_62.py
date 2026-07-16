"""Wiring smoke for 0.4.62."""
from pathlib import Path

def test_ship_0_4_62():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'runAnalyzeTimeline' in ts and 'btn-analyze-tl' in html
    assert 'runAnalyzeBinAudio' in ts and 'btn-analyze-aud' in html

