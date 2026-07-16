"""white_balance_selection + clear_selection_effects + strip path-C unmapped (0.6.36)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=white:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_wb_clear_strip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wcs_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 12)

        wb = ed.white_balance_selection([c1.id], temperature=5600.0)
        assert wb["count"] == 1
        assert any(
            isinstance(e, dict) and e.get("type") == "white_balance"
            for e in (ed._find_clip(c1.id).effects or [])
        )

        # add mapped + try strip: white_balance is mapped so strip may no-op
        ed.vignette_selection([c1.id], strength=0.3)
        strip = ed.strip_selection_path_c_unmapped([c1.id])
        assert int(strip["adapter_version"]) >= int(ADAPTER_VERSION)
        # still has effects after strip of only unmapped
        assert isinstance(strip["count"], int)

        clr = ed.clear_selection_effects([c1.id])
        assert not (ed._find_clip(c1.id).effects or [])
        assert clr.get("count") is not None or "cleared" in clr
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_36():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/white_balance_selection" in app
    assert "/api/edit/clear_selection_effects" in app
    assert "/api/edit/strip_selection_path_c_unmapped" in app
    assert "def white_balance_selection" in mcp
    assert "def clear_selection_effects" in mcp
    assert "def strip_selection_path_c_unmapped" in mcp
    assert 'id="btn-wb-sel"' in html
    assert 'id="btn-clr-fx-sel"' in html
    assert 'id="btn-strip-pathc-sel"' in html
    assert "whiteBalanceSelectionUi" in ts
    assert "clearSelectionEffectsUi" in ts
    assert "stripSelectionPathCUnmappedUi" in ts
