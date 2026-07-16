"""join_clips + paste_position + set_clips_flip (0.6.6)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )


def test_join_paste_flip():
    root = Path(tempfile.mkdtemp(prefix="opmiere_jpf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 1.0)  # ~30f at 30fps
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)
        # razor into two contiguous halves
        mid = c.start + c.timeline_duration_frames // 2
        left, right = ed.split_clip(c.id, mid)
        assert left.end == right.start
        assert left.src_out == right.src_in
        j = ed.join_clips(left.id, right.id)
        assert j["clip_id"] == left.id
        joined = ed._find_clip(left.id)
        assert joined.src_out > left.src_in
        try:
            ed._find_clip(right.id)
            assert False, "right clip should be removed"
        except Exception:
            pass

        # PiP position paste
        over = ed.add_track("video")
        a = ed.place_from_file(v, "video", over.id, 0)
        b = ed.place_from_file(v, "video", over.id, int(a.end))
        with ed._mutate():
            ed._find_clip(a.id).position = {"x": 1.0, "y": 0.0, "scale": 0.3}
        pp = ed.paste_position(a.id, [b.id])
        assert pp["count"] == 1
        assert ed._find_clip(b.id).position is not None
        assert abs(float(ed._find_clip(b.id).position["scale"]) - 0.3) < 1e-6

        fl = ed.set_clips_flip([a.id, b.id], horizontal=True)
        assert fl["count"] == 2
        for cid in (a.id, b.id):
            types = {e.get("type") for e in (ed._find_clip(cid).effects or [])}
            assert "hflip" in types
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_6():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/join_clips" in app
    assert "/api/clip/paste_position" in app
    assert "/api/clip/set_clips_flip" in app
    assert "def join_clips" in mcp
    assert "def paste_position" in mcp
    assert "def set_clips_flip" in mcp
    assert 'id="btn-join"' in html
    assert 'id="btn-paste-pos"' in html
    assert 'id="btn-flip-h"' in html
    assert "joinClipsUi" in ts
    assert "pastePositionUi" in ts
    assert "flipHSelectionUi" in ts
