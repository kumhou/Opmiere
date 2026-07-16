"""assemble_unused_media + freeze_at_markers + stills_at_markers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

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


def test_assemble_unused_media():
    root = Path(tempfile.mkdtemp(prefix="opmiere_asm_"))
    try:
        a = root / "a.mp4"
        b = root / "b.mp4"
        _vid(a, 0.5, "navy")
        _vid(b, 0.5, "olive")
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        ed.import_media(a, "video")
        ed.import_media(b, "video")
        assert ed.list_unused_media()["count"] == 2
        r = ed.assemble_unused_media(tr.id, kind="video")
        assert r["count"] == 2
        assert ed.list_unused_media()["count"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_freeze_at_markers():
    root = Path(tempfile.mkdtemp(prefix="opmiere_fam_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.5)
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        ed.add_marker(frame=c.start + 5, label="A")
        ed.add_marker(frame=c.start + 20, label="B")
        r = ed.freeze_at_markers(tr.id, duration_frames=10)
        assert r["count"] == 2
        assert len(tr.clips) >= 3
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stills_at_markers_mocked():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sam_"))
    try:
        ed = Editor.create(root / "p.opm", fps=30, width=320, height=180)
        ed.add_marker(frame=0, label="Open")
        ed.add_marker(frame=15, label="Mid")
        out = root / "stills"

        def _fake_still(path, frame, width=1280):
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xd8\xff\xd9")  # minimal jpeg-ish
            return {"path": str(p), "frame": frame}

        with mock.patch.object(ed, "export_still", side_effect=_fake_still):
            r = ed.stills_at_markers(out)
        assert r["count"] == 2
        assert r["ok"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_5_60():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/sequence/assemble_unused" in app
    assert "/api/freeze/at_markers" in app
    assert "/api/export/stills_at_markers" in app
    assert "def assemble_unused_media" in mcp
    assert "def freeze_at_markers" in mcp
    assert 'id="btn-asm-unused"' in html
    assert 'id="btn-freeze-mkr"' in html
    assert "assembleUnusedUi" in ts
