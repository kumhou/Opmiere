"""0.3.0: UI shell complete markers."""

from pathlib import Path


def test_shell_complete_markers():
    html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "opmiere"
        / "web"
        / "static"
        / "index.html"
    )
    t = html.read_text(encoding="utf-8")
    assert "UI shell complete 0.3.0" in t
    assert "shell complete 0.3.0" in t
    assert "#selCard" in t
    assert "toastHost" in t or "window.toast" in t
    assert "data-link=" in t
    # core shell regions
    for rid in (
        "topbar",
        "panel-media",
        "panel-preview",
        "panel-inspector",
        "panel-timeline",
        "dropZone",
        "ctxMenu",
        "keyHint",
        "btnToggleMedia",
        "btnToggleInspector",
        "splitHandle",
        "btnFullscreen",
    ):
        assert f'id="{rid}"' in t or f"id='{rid}'" in t, rid


def test_design_system_docs_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "design-system" / "opmiere" / "MASTER.md").is_file()
    assert (root / "design-system" / "opmiere" / "pages" / "editor-shell.md").is_file()
