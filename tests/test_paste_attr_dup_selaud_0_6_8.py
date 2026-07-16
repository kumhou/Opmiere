"""paste_from_clip + duplicate_selection + export_selection_audio (0.6.8)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_paste_from_dup_selection_audio():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pda_"))
    try:
        v = root / "v.mp4"
        _vid(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0)
        c2 = ed.place_from_file(v, "video", tr.id, int(c1.end))
        ed.apply_vignette(c1.id, strength=0.35)
        with ed._mutate():
            ed._find_clip(c1.id).position = {"x": 0.0, "y": 1.0, "scale": 0.4}
            ed._find_clip(c1.id).color = "#ff0000"
        pa = ed.paste_from_clip(
            c1.id, [c2.id], effects=True, attributes=True, color=True,
        )
        assert pa["count"] == 1
        c2b = ed._find_clip(c2.id)
        assert any(e.get("type") == "vignette" for e in (c2b.effects or []))
        assert c2b.position is not None
        assert abs(float(c2b.position["scale"]) - 0.4) < 1e-6
        assert c2b.color == "#ff0000"

        # export before duplicate (dup would overlap on contiguous base track)
        aud = ed.export_selection_audio([c1.id, c2.id], root / "sel.wav")
        assert Path(aud["path"]).exists()
        assert Path(aud["path"]).stat().st_size > 0
        assert aud["start_frame"] == c1.start

        # duplicate last clip only → lands after sequence end
        before_n = sum(len(t.clips) for t in ed.project.tracks)
        dup = ed.duplicate_selection([c2.id])
        assert dup["count"] == 1
        after_n = sum(len(t.clips) for t in ed.project.tracks)
        assert after_n == before_n + 1
        assert dup["duplicates"][0].get("clip_id")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_8():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/clip/paste_from_clip" in app
    assert "/api/edit/duplicate_selection" in app
    assert "/api/export/selection_audio" in app
    assert "def paste_from_clip" in mcp
    assert "def duplicate_selection" in mcp
    assert "def export_selection_audio" in mcp
    assert 'id="btn-paste-from"' in html
    assert 'id="btn-dup-sel"' in html
    assert 'id="btn-sel-aud"' in html
    assert "pasteFromClipUi" in ts
    assert "duplicateSelectionUi" in ts
    assert "exportSelectionAudioUi" in ts
