"""Wiring for 0.5.37 (no package-version pin)."""

from pathlib import Path

from opmiere.render.openshot_map import ADAPTER_VERSION, path_c_effect_catalog


def test_ship_0_5_37():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    assert "/api/clip/{clip_id}/path_c" in app or 'clip_id}/path_c"' in app or "/path_c" in app
    assert "clip_path_c_support" in app
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "path-C" in ts or "path-C v" in ts
    assert "/api/preview/openshot_effects" in ts
    cat = path_c_effect_catalog()
    assert int(ADAPTER_VERSION) >= 6
    assert "film_grain" in cat["mapped"]
    assert "chroma_key" in cat["mapped"]
