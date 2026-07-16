"""selection_waveforms + export_selection_manifest (0.6.52)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=teal:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=330:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_waveforms_and_manifest():
    root = Path(tempfile.mkdtemp(prefix="opmiere_wm_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)

        wf = ed.selection_waveforms([c.id], num_peaks=64)
        assert wf["count"] == 1
        assert wf["error_count"] == 0
        peaks = wf["waveforms"][0].get("peaks")
        assert peaks and len(peaks) >= 8

        man = ed.export_selection_manifest([c.id])
        p = Path(man["path"])
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["schema"] == "opmiere.selection_manifest.v1"
        assert int(data["path_c"]["adapter_version"]) >= int(ADAPTER_VERSION)
        assert data["span"]["duration_frames"] == 12
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_52():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_waveforms" in app
    assert "/api/edit/export_selection_manifest" in app
    assert "def selection_waveforms" in mcp
    assert "def export_selection_manifest" in mcp
    assert 'id="btn-wave-sel"' in html
    assert 'id="btn-manif-sel"' in html
    assert "selectionWaveformsUi" in ts
    assert "exportSelectionManifestUi" in ts
