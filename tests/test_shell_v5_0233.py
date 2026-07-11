"""0.2.33: UI shell v5 chrome markers present."""

from pathlib import Path


def test_shell_v5_markers():
    html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "opmiere"
        / "web"
        / "static"
        / "index.html"
    )
    t = html.read_text(encoding="utf-8")
    assert 'id="ctxMenu"' in t
    assert "UI shell v5" in t
    assert "shell v5" in t
    assert "audio-lane" in t or "video-lane" in t
    assert "/api/clip/copy" in t
    assert "clipboard/copy" not in t
