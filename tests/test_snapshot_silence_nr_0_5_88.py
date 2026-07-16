"""list_silence_ranges + apply_noise_reduction_to_track + export_project_snapshot (0.5.88)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_av_silence(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=f=440:d=0.3",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-f", "lavfi", "-i", "sine=f=550:d=0.3",
            "-f", "lavfi", "-i", "color=c=navy:s=160x90:d=0.95",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a];"
            "[3:v]trim=duration=0.95,setpts=PTS-STARTPTS[v]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )


def test_silence_map_nr_snapshot():
    root = Path(tempfile.mkdtemp(prefix="opmiere_snap_"))
    try:
        v = root / "v.mp4"
        _vid_av_silence(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        sil = ed.list_silence_ranges(clip_id=c.id, noise_db=-40, min_duration=0.12)
        assert "count" in sil
        assert "ranges" in sil
        nr = ed.apply_noise_reduction_to_track(tr.id, amount=10.0)
        assert nr["count"] == 1
        assert any(
            e.get("type") == "noise_reduction" for e in (c.effects or [])
        )
        snap = root / "snap.json"
        r = ed.export_project_snapshot(snap)
        assert Path(r["path"]).is_file()
        doc = json.loads(snap.read_text(encoding="utf-8"))
        assert doc["schema"] == "opmiere.project_snapshot.v1"
        assert "project" in doc
        assert "media_status" in doc
        assert r["clip_count"] >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_88():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/analyze/silence_ranges" in app
    assert "/api/track/noise_reduction" in app
    assert "/api/export/project_snapshot" in app
    assert "def list_silence_ranges" in mcp
    assert "def export_project_snapshot" in mcp
    assert 'id="btn-snapshot"' in html
    assert "projectSnapshotUi" in ts
