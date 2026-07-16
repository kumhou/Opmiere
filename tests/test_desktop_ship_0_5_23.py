"""Wiring for 0.5.23."""
from pathlib import Path

def test_ship_0_5_23():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    app = (root / "src" / "opmiere" / "web" / "app.py").read_text(encoding="utf-8")
    m = (root / 'src/opmiere/render/openshot_map.py').read_text(encoding='utf-8')
    assert 'adapter_version' in m and 'blur' in m
    assert 'collectGenParams' in ts and 'btn-pro-toggle' in html

