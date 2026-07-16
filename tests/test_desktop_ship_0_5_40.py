"""Wiring for 0.5.40 project path-C report (no package-version pin)."""

from pathlib import Path

from opmiere import Editor
from opmiere.render.openshot_map import project_path_c_report
import shutil
import subprocess
import tempfile


def _vid(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=purple:s=160x90:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_ship_0_5_40_wiring():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/project/path_c" in app
    assert "def project_path_c" in mcp
    assert 'id="btn-pathc-report"' in html
    assert "pathCReportUi" in ts


def test_project_path_c_report():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pcrep_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.apply_effect(c.id, {"type": "blur", "amount": 1.0})
        ed.apply_effect(
            c.id,
            {
                "type": "text",
                "content": "x",
                "position": "bottom",
                "size": 24,
                "border_width": 1,
            },
        )
        rep = project_path_c_report(ed.project)
        assert rep["clips_with_effects"] == 1
        assert rep["not_ready_count"] == 1
        assert rep["path_c_ready"] is False
        assert "text" in rep["clips"][0]["unmapped"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
