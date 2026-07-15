"""Desktop ensure_core_api wiring smoke (0.4.35)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ensure_core_rust_and_ui():
    lib = (ROOT / "ui-desktop" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "fn ensure_core_api" in lib
    assert "opmiere.web.app" in lib
    assert "install.json" in lib

    perm = (ROOT / "ui-desktop" / "src-tauri" / "permissions" / "ensure-core-api.toml").read_text(
        encoding="utf-8"
    )
    assert "allow-ensure-core-api" in perm
    assert "ensure_core_api" in perm

    cap = (ROOT / "ui-desktop" / "src-tauri" / "capabilities" / "default.json").read_text(
        encoding="utf-8"
    )
    assert "allow-ensure-core-api" in cap

    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "tryEnsureCoreApi" in ts
    assert "ensure_core_api" in ts
