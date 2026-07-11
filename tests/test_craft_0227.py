"""0.2.27: prepare_for_export, hard_cut_all, batch_relink, clips_sharing_media."""

from __future__ import annotations

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


def test_prepare_hardcut_relink_share(tmp_path: Path):
    v = tmp_path / "a.mp4"
    v2 = tmp_path / "b.mp4"
    _vid(v, "red", 1.5)
    _vid(v2, "blue", 1.5)
    ed = Editor.create(tmp_path / "p.opm", fps=FPS, width=160, height=90)
    tr = ed.add_track("video")
    c1 = ed.place_from_file(v, "video", tr.id, 0)
    c2 = ed.add_clip(tr.id, ed.project.media[0].id, c1.end, 0, 30)
    ed.apply_transitions_on_cuts(tr.id, duration_frames=6)
    assert ed._find_clip(c2.id).transition_in is not None

    hc = ed.hard_cut_all(tr.id)
    assert hc["transitions_cleared"] >= 1
    assert ed._find_clip(c2.id).transition_in is None
    assert ed._find_clip(c2.id).start == ed._find_clip(c1.id).end

    m2 = ed.import_media(v2, "video")
    share = ed.clips_sharing_media(ed.project.media[0].id)
    assert share["count"] >= 1
    br = ed.batch_relink({c1.id: m2.id})
    assert br["count"] == 1
    assert ed._find_clip(c1.id).media == m2.id

    # gap then prepare
    with ed._mutate():
        ed._find_clip(c2.id).start += 10
    prep = ed.prepare_for_export(fill_video=True)
    assert "ready" in prep
    assert "validate" in prep
