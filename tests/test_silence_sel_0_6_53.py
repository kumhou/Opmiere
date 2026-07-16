"""silence split/suggest/apply on selection (0.6.53)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from opmiere import Editor


def _vid_with_silence(path: Path) -> None:
    # 0.4s tone + 0.5s silence + 0.4s tone
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=160x90:d=1.3",
            "-f", "lavfi", "-i", "sine=f=440:d=0.4",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=0.5",
            "-f", "lavfi", "-i", "sine=f=440:d=0.4",
            "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )


def test_silence_selection_apis():
    root = Path(tempfile.mkdtemp(prefix="opmiere_sil_"))
    try:
        v = root / "v.mp4"
        _vid_with_silence(v)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0)

        plan = ed.suggest_silence_cuts_selection([c.id])
        assert plan["count"] == 1
        assert plan["error_count"] == 0
        assert "keep_ranges" in plan["plans"][0] or "silences" in plan["plans"][0]

        dry = ed.apply_silence_to_selection([c.id], dry_run=True)
        assert dry["dry_run"] is True
        assert dry["count"] == 1

        sp = ed.split_selection_at_silences([c.id], noise_db=-35.0, min_duration=0.2)
        assert "total_splits" in sp
        assert sp["error_count"] == 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_6_53():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/split_selection_at_silences" in app
    assert "/api/edit/suggest_silence_cuts_selection" in app
    assert "/api/edit/apply_silence_to_selection" in app
    assert "def split_selection_at_silences" in mcp
    assert "def suggest_silence_cuts_selection" in mcp
    assert "def apply_silence_to_selection" in mcp
    assert 'id="btn-sil-split-sel"' in html
    assert 'id="btn-sil-plan-sel"' in html
    assert 'id="btn-sil-dry-sel"' in html
    assert "splitSelectionAtSilencesUi" in ts
    assert "suggestSilenceCutsSelectionUi" in ts
    assert "applySilenceSelectionDryUi" in ts
