"""Wiring for 0.5.38 path-C MCP tools (no package-version pin)."""

from pathlib import Path

from opmiere.render.openshot_map import ADAPTER_VERSION, path_c_effect_catalog


def test_ship_0_5_38():
    root = Path(__file__).resolve().parents[1]
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    assert "def path_c_effect_catalog" in mcp
    assert "def clip_path_c" in mcp
    cat = path_c_effect_catalog()
    assert int(ADAPTER_VERSION) >= 7
    assert "luma_key" in cat["mapped"]
