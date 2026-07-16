"""Wiring for 0.5.0."""
from pathlib import Path

def test_ship_0_5_0():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert '0.5.0' in (root / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'btn-pro-toggle' in html and 'collectGenParams' in ts
    assert 'adapter_version' in (root / 'src/opmiere/render/openshot_map.py').read_text(encoding='utf-8')

