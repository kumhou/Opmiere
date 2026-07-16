"""Wiring for 0.5.36 path-C adapter v5 (no package-version pin)."""

from pathlib import Path

from opmiere.render.openshot_map import ADAPTER_VERSION, path_c_effect_catalog


def test_ship_0_5_36():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    assert "/api/preview/openshot_effects" in app
    assert "path_c_effect_catalog" in app
    cat = path_c_effect_catalog()
    assert int(cat.get("adapter_version") or 0) >= 5
    assert int(ADAPTER_VERSION) >= 5
    assert "vignette" in cat["mapped"]
    assert "ken_burns" in cat["mapped"]
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    # Desktop already exposes these effect presets; adapter now maps them.
    assert "vignette" in ts and "ken_burns" in ts
