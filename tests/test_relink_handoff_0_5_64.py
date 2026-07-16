"""relink_offline_media + export_handoff_package (0.5.64)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5, color: str = "navy") -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_relink_offline_media_by_basename():
    root = Path(tempfile.mkdtemp(prefix="opmiere_relink_"))
    try:
        src = root / "shot_a.mp4"
        _vid(src)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        m = ed.import_media(src, "video")
        # remove file from bundle to simulate offline
        dest = ed.bundle.media_path(m.path)
        assert dest.exists()
        dest.unlink()
        st = ed.list_media_status()
        assert st["offline_count"] == 1

        search = root / "found"
        search.mkdir()
        recovery = search / Path(m.path).name
        shutil.copy2(src, recovery)

        r = ed.relink_offline_media([search], recursive=True, re_probe=True)
        assert r["count"] == 1
        assert r["still_offline_count"] == 0
        assert ed.bundle.media_path(m.path).exists()
        assert ed.list_media_status()["ok"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_export_handoff_package():
    root = Path(tempfile.mkdtemp(prefix="opmiere_hand_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=10, label="Beat")
        out = root / "handoff_out"
        r = ed.export_handoff_package(out)
        assert r["count"] >= 4
        assert (out / "edit_manifest.json").is_file()
        assert (out / "media_status.json").is_file()
        assert (out / "preflight.json").is_file()
        assert (out / "youtube_chapters.txt").is_file()
        assert (out / "handoff.json").is_file()
        body = (out / "youtube_chapters.txt").read_text(encoding="utf-8")
        assert "Beat" in body or "0:00" in body
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_64():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/media/relink_offline" in app
    assert "/api/export/handoff" in app
    assert "def relink_offline_media" in mcp
    assert "def export_handoff_package" in mcp
    assert 'id="btn-relink-off"' in html
    assert 'id="btn-handoff"' in html
    assert "relinkOfflineUi" in ts
    assert "exportHandoffUi" in ts
