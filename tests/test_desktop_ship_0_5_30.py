"""Wiring for 0.5.30."""
from pathlib import Path

def test_ship_0_5_30():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'collectGenParams' in ts and 'btn-pro-toggle' in html
    assert 'adapter_version' in (root/'src/opmiere/render/openshot_map.py').read_text(encoding='utf-8')

