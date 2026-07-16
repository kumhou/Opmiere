"""Wiring for 0.5.39 path-C status pill (no package-version pin)."""

from pathlib import Path


def test_ship_0_5_39():
    root = Path(__file__).resolve().parents[1]
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert 'id="pill-pathc"' in html
    assert "pill-pathc" in ts
    assert "/api/preview/openshot_effects" in ts
    assert "path-C v" in ts
