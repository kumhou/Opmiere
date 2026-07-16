"""Wiring for 0.4.92."""
from pathlib import Path

def test_ship_0_4_92():
    root = Path(__file__).resolve().parents[1]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    m = (root / 'src/opmiere/render/openshot_map.py').read_text(encoding='utf-8')
    assert 'adapter_version' in m
    assert '4' in m
    assert 'blur' in m and 'fade_in_frames' in m

