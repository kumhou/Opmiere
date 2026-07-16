"""Wiring for 0.4.72."""
from pathlib import Path

def test_ship_0_4_72():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'detectBeatsUi' in ts and 'btn-det-beats' in html
    assert 'suggestMixUi' in ts and 'btn-mix-plan' in html

