"""Desktop zoom fit / zoom selection (0.4.43)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_zoom_fit_sel_wiring():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "zoomFitSequence" in ts
    assert "zoomToSelection" in ts
    assert 'k === "z"' in ts
    html = (ROOT / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-zoom-fit"' in html
    assert 'id="btn-zoom-sel"' in html
