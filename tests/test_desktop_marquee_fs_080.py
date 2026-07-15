"""Desktop marquee select + fullscreen + Home/End (0.4.40)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_marquee_fullscreen_wiring():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "wireTimelineMarquee" in ts
    assert "marqueeDrag" in ts
    assert "toggleProgramFullscreen" in ts
    assert "requestFullscreen" in ts
    assert 'ev.key === "Home"' in ts
    assert 'ev.key === "End"' in ts
    html = (ROOT / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-fs"' in html
    css = (ROOT / "ui-desktop" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "#marquee" in css
    assert "fullscreen" in css
