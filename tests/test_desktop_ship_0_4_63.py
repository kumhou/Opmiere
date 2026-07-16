"""Wiring smoke for 0.4.63."""
from pathlib import Path

def test_ship_0_4_63():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'runSilenceCutsPlan' in ts and 'btn-silence' in html
    assert 'runDetectScenes' in ts and 'btn-scenes' in html

