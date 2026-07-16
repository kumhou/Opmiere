"""Wiring for 0.5.4."""
from pathlib import Path

def test_ship_0_5_4():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'btn-preflight' in html
    assert 'submitGeneration' in ts
    assert 'runAgentPreflight' in ts

