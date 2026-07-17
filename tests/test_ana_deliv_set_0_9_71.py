"""analyze_selection_set_audio + delivery_check_selection_set (0.9.71)."""

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


def test_analyze_audio_and_delivery_check_on_set():
    root = Path(tempfile.mkdtemp(prefix="opmiere_anadel_"))
    try:
        v = root / "v.mp4"
        _vid(v, 0.5)
        ed = Editor.create(root / "p.opm", fps=30, width=160, height=90)
        tr = ed.add_track("video")
        c = ed.place_from_file(v, "video", tr.id, 0, duration_frames=12)
        ed.save_selection_set("hero", [c.id])

        an = ed.analyze_selection_set_audio(
            "hero", filename="hero_mix_analyze.wav",
        )
        assert an.get("selection_set") == "hero"
        assert an.get("selection_audio_path") or an.get("path")

        dc = ed.delivery_check_selection_set(
            "hero",
            filename="hero_delivery.mp4",
            preset="streaming",
        )
        assert dc.get("selection_set") == "hero"
        assert dc.get("export_path") or dc.get("path")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_ship_wiring_0_9_71():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/opmiere/web/app.py").read_text(encoding="utf-8")
    mcp = (root / "src/opmiere/mcp_server.py").read_text(encoding="utf-8")
    html = (root / "ui-desktop" / "index.html").read_text(encoding="utf-8")
    ts = (root / "ui-desktop" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "/api/edit/analyze_selection_set_audio" in app
    assert "/api/edit/delivery_check_selection_set" in app
    assert "def analyze_selection_set_audio" in mcp
    assert "def delivery_check_selection_set" in mcp
    assert 'id="btn-an-audio-set"' in html
    assert 'id="btn-deliv-set"' in html
    assert "analyzeSelectionSetAudioUi" in ts
    assert "deliveryCheckSelectionSetUi" in ts
    from opmiere import Editor as Ed

    cat = Ed.selection_set_tool_catalog()
    assert "analyze_selection_set_audio" in cat["tool_ids"]
    assert "delivery_check_selection_set" in cat["tool_ids"]
