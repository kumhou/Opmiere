"""pack_selection_set + detach_audio_selection_set (0.9.41)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid(path: Path, d: float = 0.5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=dimgray:s=160x90:d={d}",
            "-f", "lavfi", "-i", f"sine=f=85:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_pack_and_detach_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_pd_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c1 = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        c2 = ed.place_from_file(v, "video", tr.id, 30, duration_frames=12)
        ed.save_selection_set("hero", [c1.id, c2.id])

        packed = ed.pack_selection_set("hero", gap_frames=0)
        assert packed.get("selection_set") == "hero"
        assert int(ed._find_clip(c2.id).start) == 12

        det = ed.detach_audio_selection_set("hero")
        assert det.get("selection_set") == "hero"
        assert "count" in det
        assert "skipped_count" in det
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_41():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/pack_selection_set" in app
    assert "/api/edit/detach_audio_selection_set" in app
    assert "def pack_selection_set" in mcp
    assert "def detach_audio_selection_set" in mcp
    assert 'id="btn-pack-set"' in html
    assert 'id="btn-detach-set"' in html
    assert "packSelectionSetUi" in ts
    assert "detachAudioSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "pack_selection_set" in cat["tool_ids"]
    assert "detach_audio_selection_set" in cat["tool_ids"]
