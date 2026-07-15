"""Desktop filler cut wiring (0.4.47)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_filler_ui_wiring():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "fillerCutsSelection" in ts
    assert "/api/filler" in ts
    assert "dry_run" in ts
    html = (ROOT / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-filler-plan"' in html
    assert 'id="btn-filler-go"' in html
