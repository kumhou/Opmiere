"""Wiring smoke for 0.4.66."""
from pathlib import Path

def test_ship_0_4_66():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'deleteTrackOfSelection' in ts and 'btn-del-trk' in html
    assert 'hardCutAllUi' in ts and 'btn-hard-cut' in html

