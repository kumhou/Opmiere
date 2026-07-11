"""0.2.34: UI shell v6 markers."""

from pathlib import Path


def test_shell_v6_markers():
    html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "opmiere"
        / "web"
        / "static"
        / "index.html"
    )
    t = html.read_text(encoding="utf-8")
    assert "UI shell v6" in t
    assert "shell v6" in t
    assert "tn-title" in t
    assert "#marquee" in t
    assert "btnZoomIn" in t or "btnZoomOut" in t or "Zoom in" in t
    # track-lane class template must be valid JS (no backslash-escaped quotes)
    assert "\\'audio-lane\\'" not in t
    assert "audio-lane" in t
