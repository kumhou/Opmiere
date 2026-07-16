"""selection_export_preflight + offline + locked tracks (0.6.44)."""

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
            "-f", "lavfi", "-i", f"color=c=gray:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_preflight_offline_locked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pol_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        med = ed.import_media(v, "video")
        c1 = ed.add_clip(tr.id, med.id, 0, 0, 10)
        c2 = ed.add_clip(tr.id, med.id, 20, 0, 10)

        off = ed.selection_offline_media([c1.id, c2.id])
        assert off["ok"] is True
        assert off["offline_count"] == 0

        lk = ed.selection_locked_tracks([c1.id])
        assert lk["ok"] is True
        assert lk["locked_count"] == 0

        pf = ed.selection_export_preflight([c1.id, c2.id], set_work_area=True)
        assert pf["soft_ready"] is True
        assert pf["offline_count"] == 0
        assert pf["gap_count"] >= 1
        assert int(pf["path_c"]["adapter_version"]) >= int(ADAPTER_VERSION)
        assert pf["work_area"] and pf["work_area"].get("ready") is True
        assert pf["span"]["start_frame"] == 0
        assert pf["span"]["end_frame"] == 30
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_44():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_export_preflight" in app
    assert "/api/edit/selection_offline_media" in app
    assert "/api/edit/selection_locked_tracks" in app
    assert "def selection_export_preflight" in mcp
    assert "def selection_offline_media" in mcp
    assert "def selection_locked_tracks" in mcp
    assert 'id="btn-preflight-sel"' in html
    assert 'id="btn-offline-sel"' in html
    assert 'id="btn-locked-sel"' in html
    assert "selectionExportPreflightUi" in ts
    assert "selectionOfflineMediaUi" in ts
    assert "selectionLockedTracksUi" in ts
