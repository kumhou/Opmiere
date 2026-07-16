"""Wiring for 0.4.91."""
from pathlib import Path

def test_ship_0_4_91():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'btn-pro-toggle' in html and 'btn-doctor-full' in html
    assert 'showDoctorFull' in ts and 'pro-body' in html

