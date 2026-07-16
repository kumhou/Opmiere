"""Wiring for 0.4.98."""
from pathlib import Path

def test_ship_0_4_98():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'session-stats' in html and 'bumpSessionStats' in ts

