"""Desktop dirty close/open guard + auto-proxy (0.4.45)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dirty_and_auto_proxy_wiring():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "confirmLeaveDirty" in ts
    assert "scheduleProxyRefresh" in ts
    assert "chk-auto-proxy" in ts
    assert "Save before closing" in ts
    html = (ROOT / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="chk-auto-proxy"' in html
