"""Wiring for 0.5.27."""
from pathlib import Path

def test_ship_0_5_27():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'exportStillUi' in ts and 'preview/frame.jpg' in ts

