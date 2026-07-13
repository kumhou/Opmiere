"""Desktop packaging config smoke (0.4.32)."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAURI_CONF = ROOT / "ui-desktop" / "src-tauri" / "tauri.conf.json"
BUILD_PS1 = ROOT / "scripts" / "build-desktop.ps1"
PKG = ROOT / "ui-desktop" / "package.json"


def test_tauri_nsis_bundle_config():
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    assert conf["productName"] == "Opmiere"
    assert conf["bundle"]["active"] is True
    targets = conf["bundle"]["targets"]
    assert targets == ["nsis"] or targets == "nsis"
    assert "icons/icon.ico" in conf["bundle"]["icon"]
    win = conf["bundle"].get("windows") or {}
    assert "nsis" in win
    assert conf["version"].startswith("0.4.")


def test_build_script_and_npm_script_exist():
    assert BUILD_PS1.is_file()
    text = BUILD_PS1.read_text(encoding="utf-8")
    assert "tauri build" in text
    assert "vcvars" in text.lower() or "BuildTools" in text
    assert ".cargo" in text  # cargo PATH re-prepend after vcvars

    pkg = json.loads(PKG.read_text(encoding="utf-8"))
    assert "tauri:build" in pkg.get("scripts", {})
