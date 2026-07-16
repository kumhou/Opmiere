"""export_marker_segments social chapter cuts."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from opmiere import Editor


def _vid(path: Path, d: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_export_marker_segments_with_mock_export():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ems_"))
    try:
        v = root / "v.mp4"
        _vid(v, 2.0)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=0, label="Intro")
        ed.add_marker(frame=30, label="Body")
        out_dir = root / "segs"

        def _fake_export(path, normalize_preset=None):
            # write a real short mp4 so ffmpeg trim has input
            p = Path(path)
            _vid(p, 2.0)
            return p

        with mock.patch.object(ed, "export", side_effect=_fake_export):
            r = ed.export_marker_segments(out_dir, name_prefix="cut", include_tail=True)
        assert r["count"] >= 1
        assert r["ok"] is True
        assert Path(r["output_dir"]).is_dir()
        paths = [s["path"] for s in r["segments"] if s.get("ok")]
        assert paths
        assert all(Path(p).is_file() for p in paths)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_marker_segments_requires_markers():
    root = Path(tempfile.mkdtemp(prefix="opmiere_ems2_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        try:
            ed.export_marker_segments(root / "out")
            assert False, "expected ValueError"
        except ValueError as e:
            assert "no markers" in str(e).lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_52():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/marker_segments" in app
    assert "def export_marker_segments" in mcp
    assert 'id="btn-exp-mkr-seg"' in html
    assert "exportMarkerSegmentsUi" in ts
