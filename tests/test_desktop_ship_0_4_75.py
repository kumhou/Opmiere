"""Wiring for 0.4.75."""
from pathlib import Path

def test_ship_0_4_75():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'clipsSharingMediaUi' in ts and 'placeAfterUi' in ts
    assert 'btn-share-media' in html and 'btn-place-after' in html

