"""selection_agent_preflight + export_selection_manifest_default (0.6.56)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import ADAPTER_VERSION


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_agent_preflight_and_manifest_default():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ap_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        pre = ed.selection_agent_preflight([c.id], set_work_area=False)
        assert "ready" in pre
        assert "next_steps" in pre
        assert isinstance(pre["next_steps"], list)
        assert int(pre.get("adapter_version") or 0) >= int(ADAPTER_VERSION) or (
            pre.get("adapter_version") is not None
        )
        assert pre.get("clip_count") == 1

        man = ed.export_selection_manifest_default(
            [c.id], filename="sel_man.json",
        )
        p = Path(man.get("path") or "")
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("schema") == "opmiere.selection_manifest.v1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_56():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_agent_preflight" in app
    assert "/api/edit/export_selection_manifest_default" in app
    assert "def selection_agent_preflight" in mcp
    assert "def export_selection_manifest_default" in mcp
    assert 'id="btn-agent-pre-sel"' in html
    assert 'id="btn-manif-def-sel"' in html
    assert "selectionAgentPreflightUi" in ts
    assert "exportSelectionManifestDefaultUi" in ts
