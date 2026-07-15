"""Desktop lifecycle + title + reopen wiring (0.4.36)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lifecycle_and_title_wiring():
    lib = (ROOT / "ui-desktop" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "fn stop_core_api" in lib
    assert "OWNED_CORE_PID" in lib
    assert "RunEvent::Exit" in lib
    assert "taskkill" in lib or "kill_pid" in lib

    perm = (ROOT / "ui-desktop" / "src-tauri" / "permissions" / "ensure-core-api.toml").read_text(
        encoding="utf-8"
    )
    assert "allow-stop-core-api" in perm
    assert "stop_core_api" in perm

    cap = (ROOT / "ui-desktop" / "src-tauri" / "capabilities" / "default.json").read_text(
        encoding="utf-8"
    )
    assert "allow-stop-core-api" in cap
    assert "core:window:allow-set-title" in cap

    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "setShellTitle" in ts
    assert "maybeAutoOpenRecent" in ts
    assert "didAutoOpenRecent" in ts
    assert "setTitle" in ts
