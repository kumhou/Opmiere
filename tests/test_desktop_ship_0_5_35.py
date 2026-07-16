"""Wiring for 0.5.35."""
from pathlib import Path

def test_ship_0_5_35():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'runAgentPreflight' in ts and 'submitGeneration' in ts
    assert 'btn-preflight' in html and 'btn-gen-go' in html

