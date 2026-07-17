"""audio_eq_selection_set + reverse_selection_set (0.9.49)."""

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


def test_audio_eq_and_reverse_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_eqrev_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        eq = ed.audio_eq_selection_set(
            "hero", frequency_hz=2000.0, gain_db=3.0, q=1.0,
        )
        assert eq.get("selection_set") == "hero"
        assert eq.get("frequency_hz") == 2000.0
        assert eq.get("gain_db") == 3.0
        assert "count" in eq

        rev = ed.reverse_selection_set("hero", replace=True)
        assert rev.get("selection_set") == "hero"
        assert "count" in rev
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_49():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/audio_eq_selection_set" in app
    assert "/api/edit/reverse_selection_set" in app
    assert "def audio_eq_selection_set" in mcp
    assert "def reverse_selection_set" in mcp
    assert 'id="btn-eq-set"' in html
    assert 'id="btn-rev-set"' in html
    assert "audioEqSelectionSetUi" in ts
    assert "reverseSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "audio_eq_selection_set" in cat["tool_ids"]
    assert "reverse_selection_set" in cat["tool_ids"]
