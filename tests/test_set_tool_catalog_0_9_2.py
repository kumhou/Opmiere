"""selection_set_tool_catalog + export (0.9.2)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from opmiere import Editor


def test_catalog_and_export():
    root = Path(tempfile.mkdtemp(prefix="opmiere_stc_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)

        cat = ed.selection_set_tool_catalog()
        assert cat.get("ok") is True
        assert cat.get("count", 0) >= 40
        assert "save_selection_set" in cat["tool_ids"]
        assert "export_selection_set_mp4" in cat["tool_ids"]
        assert "selection_set_tool_catalog" in cat["tool_ids"]
        assert len(cat.get("categories") or []) >= 5

        exp = ed.export_selection_set_tool_catalog(write_markdown=True)
        assert exp.get("ok") is True
        path = Path(exp["path"])
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("schema") == "opmiere.selection_set_tool_catalog.v1"
        assert Path(exp["markdown_path"]).is_file()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_2():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_tool_catalog" in app
    assert "/api/edit/export_selection_set_tool_catalog" in app
    assert "def selection_set_tool_catalog" in mcp
    assert "def export_selection_set_tool_catalog" in mcp
    assert 'id="btn-set-tools"' in html
    assert 'id="btn-set-tools-exp"' in html
    assert "selectionSetToolCatalogUi" in ts
    assert "exportSelectionSetToolCatalogUi" in ts
