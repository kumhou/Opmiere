"""0.2.28: FCPXML, OTIO-like JSON, agent_preflight."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from opmiere import Editor

FPS = 30


def _vid(path: Path, color: str = "green", dur: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c={color}:size=160x90:duration={dur}:rate={FPS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ],
        capture_output=True, text=True, check=True,
    )


def test_fcpxml_otio_preflight(tmp_path: Path):
    v = tmp_path / "clip.mp4"
    _vid(v, "teal", 1.0)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    ed.place_from_file(v, "video", tr.id, 0)

    fx = ed.export_fcpxml(tmp_path / "out.fcpxml", title="Test")
    assert fx["count"] >= 1
    assert "fcpxml" in fx["body"]
    assert (tmp_path / "out.fcpxml").exists()

    ot = ed.export_otio_json(tmp_path / "out.otio.json")
    assert ot["count"] >= 1
    doc = json.loads(ot["body"])
    assert doc["OTIO_SCHEMA"] == "Timeline.1"
    assert doc["tracks"]["children"]

    pf = ed.agent_preflight()
    assert "media" in pf and "validate" in pf and "duration" in pf
    assert pf["media"]["ok"] is True
