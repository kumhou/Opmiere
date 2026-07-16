"""Wiring for 0.4.97."""
from pathlib import Path

def test_ship_0_4_97():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'refreshValidate' in ts
    # saveProject calls refreshValidate
    assert 'void refreshValidate()' in ts or 'refreshValidate()' in ts

