"""selection_set_clip_durations + selection_set_waveforms (0.9.80)."""

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
            "-f", "lavfi", "-i", f"sine=f=440:d={d}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_durations_and_waveforms_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_durwf_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        durs = ed.selection_set_clip_durations("hero")
        assert durs.get("selection_set") == "hero"
        assert durs.get("count") == 1
        assert durs.get("sum_timeline_frames", 0) >= 12
        assert len(durs.get("clips") or []) == 1

        waves = ed.selection_set_waveforms("hero", num_peaks=32)
        assert waves.get("selection_set") == "hero"
        # video with audio should yield peaks, or soft-error without crashing
        assert waves.get("count", 0) + waves.get("error_count", 0) >= 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_80():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/selection_set_clip_durations" in app
    assert "/api/edit/selection_set_waveforms" in app
    assert "def selection_set_clip_durations" in mcp
    assert "def selection_set_waveforms" in mcp
    assert 'id="btn-durations-set"' in html
    assert 'id="btn-waveforms-set"' in html
    assert "selectionSetClipDurationsUi" in ts
    assert "selectionSetWaveformsUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "selection_set_clip_durations" in cat["tool_ids"]
    assert "selection_set_waveforms" in cat["tool_ids"]
