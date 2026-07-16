"""safe_area effect + export_cuts_report + path-C v23 (0.5.82)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.model import KNOWN_EFFECT_TYPES
from opmiere.render.openshot_map import ADAPTER_VERSION, path_c_effect_catalog


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_safe_area_and_cuts_report():
    assert "safe_area" in KNOWN_EFFECT_TYPES
    assert int(ADAPTER_VERSION) >= 23
    cat = path_c_effect_catalog()
    assert "safe_area" in cat["mapped"]

    root = Path(tempfile.mkdtemp(prefix="opmiere_safe_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a)
        _vid(b)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        r = ed.set_clip_safe_area(c1.id, action=0.9, title=0.8)
        assert r["enabled"] is True
        assert any(e.get("type") == "safe_area" for e in (c1.effects or []))
        trk = ed.apply_safe_area_to_track(tr.id)
        assert trk["count"] == 2
        out = root / "cuts.json"
        rep = ed.export_cuts_report(out, track_id=tr.id, format="json")
        assert Path(rep["path"]).is_file()
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["schema"] == "opmiere.cuts.v1"
        assert doc["hard_cut_count"] >= 1
        csv = ed.export_cuts_report(root / "cuts.csv", track_id=tr.id, format="csv")
        assert "frame,kind" in Path(csv["path"]).read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_82():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/safe_area" in app
    assert "/api/export/cuts_report" in app
    assert "def set_clip_safe_area" in mcp
    assert "def export_cuts_report" in mcp
    assert 'id="btn-safe"' in html
    assert "safeAreaSelectionUi" in ts
