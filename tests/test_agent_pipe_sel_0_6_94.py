"""agent_finish_selection + run_selection_pipeline (0.6.94)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=650:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_agent_finish_and_pipeline():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ap_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.4)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=10)

        fin = ed.agent_finish_selection(
            [c.id],
            repair=True,
            export=True,
            write_checklist=True,
            write_card=True,
            ensure_proxies=False,
            normalize_preset=None,
            filename="agent_fin.mp4",
        )
        assert fin.get("ok") is True
        assert fin.get("exported") is True
        assert Path(fin.get("export_path") or "").is_file()

        pipe = ed.run_selection_pipeline(
            [c.id],
            steps=["validate", "checklist"],
        )
        assert pipe.get("ok") is True
        assert len(pipe.get("results") or []) == 2
        assert all(r.get("ok") for r in pipe["results"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_94():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/agent_finish_selection" in app
    assert "/api/edit/run_selection_pipeline" in app
    assert "def agent_finish_selection" in mcp
    assert "def run_selection_pipeline" in mcp
    assert 'id="btn-agent-fin-sel"' in html
    assert 'id="btn-pipe-sel"' in html
    assert "agentFinishSelectionUi" in ts
    assert "runSelectionPipelineUi" in ts
