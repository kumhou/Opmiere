"""collect_to_bundle + replace_media_everywhere (0.5.65)."""

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


def test_collect_to_bundle():
    root = Path(tempfile.mkdtemp(prefix="opmiere_collect_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        unused = root / "unused.mp4"
        _vid(a, 0.5, "navy")
        _vid(b, 0.5, "maroon")
        _vid(unused, 0.4, "gray")
        ed = Editor.create(root / "src.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(a, "video", tr.id, 0)
        ed.place_from_file(b, "video", tr.id, c1.end)
        ed.import_media(unused, "video")  # bin only
        ed.add_marker(frame=3, label="hit")
        ed.apply_effect(c1.id, {"type": "blur", "amount": 1.5})
        dest = root / "collected.opm"
        r = ed.collect_to_bundle(dest, used_only=True)
        assert dest.is_dir()
        assert (dest / "project.json").is_file()
        assert r["clip_count"] == 2
        assert r["imported_media_count"] == 2
        other = Editor.open(dest)
        assert len(other.project.tracks[0].clips) == 2
        assert any(m.label == "hit" for m in other.project.markers)
        assert any(
            e.get("type") == "blur"
            for e in other.project.tracks[0].clips_in_order()[0].effects
        )
        # unused media not collected when used_only
        assert len(other.project.media) == 2
        assert other.list_media_status()["ok"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_replace_media_everywhere():
    root = Path(tempfile.mkdtemp(prefix="opmiere_rpl_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.6, "teal")
        _vid(b, 0.6, "orange")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        m_old = ed.import_media(a, "video")
        c1 = ed.add_clip(tr.id, m_old.id, 0, 0, min(10, m_old.duration_frames))
        c2 = ed.add_clip(
            tr.id, m_old.id, c1.end, 0, min(10, m_old.duration_frames),
        )
        m_new = ed.import_media(b, "video")
        r = ed.replace_media_everywhere(m_old.id, m_new.id, keep_source_range=True)
        assert r["count"] == 2
        assert all(c.media == m_new.id for c in tr.clips)
        assert c2.media == m_new.id
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_65():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/export/collect_bundle" in app
    assert "/api/media/replace_everywhere" in app
    assert "def collect_to_bundle" in mcp
    assert "def replace_media_everywhere" in mcp
    assert 'id="btn-collect"' in html
    assert "collectBundleUi" in ts
