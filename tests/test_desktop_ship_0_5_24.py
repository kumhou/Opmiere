"""Wiring for 0.5.24."""
from pathlib import Path

def test_ship_0_5_24():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    app = (root / "src" / "opmiere" / "web" / "app.py").read_text(encoding="utf-8")
    assert 'suggest/filler' in ts or 'suggestFillerUi' in ts

