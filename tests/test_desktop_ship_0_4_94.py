"""Wiring for 0.4.94."""
from pathlib import Path

def test_ship_0_4_94():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'framesToTc(start' in ts or 't0 = framesToTc' in ts
    assert 'drag · edges · right-click menu' in ts

