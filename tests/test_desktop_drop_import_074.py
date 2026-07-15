"""Desktop drag-drop import wiring smoke (0.4.34)."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_drop_import_wiring_in_shell():
    ts = (ROOT / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "wireTauriFileDrop" in ts
    assert "wireBrowserFileDrop" in ts
    assert "onDragDropEvent" in ts
    assert "importLocalPaths" in ts
    assert 'k === "i"' in ts and "startImport" in ts

    html = (ROOT / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    assert 'id="media-panel"' in html
    assert "Ctrl+I" in html or "drop files" in html.lower() or "Drop media" in html

    css = (ROOT / "ui-desktop" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "drop-active" in css
