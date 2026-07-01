"""P1.7 proof: transitions work through the real Editor -> FFmpegBackend path
(not just the standalone ffmpeg spike used to verify xfade/acrossfade math).

3 clips (red/green/blue, distinct colors so a wrong blend point is obvious):
  clip A -> clip B: cross-dissolve (declared via Editor.add_transition)
  clip B -> clip C: plain hard cut (untouched)

Run:  python examples/p1_7_transitions_demo.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opmiere import Editor  # noqa: E402
from opmiere.render import probe  # noqa: E402

WORKDIR = Path(__file__).resolve().parent / "_p1_7_run"
FPS = 30


def make_solid(path: Path, color: str, seconds: float) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={color}:size=320x180:duration={seconds}:rate={FPS}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def extract_frame(video_path: Path, at_seconds: float, out_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video_path),
         "-frames:v", "1", str(out_path)],
        capture_output=True, text=True, check=True,
    )


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    src_a, src_b, src_c = WORKDIR / "a.mp4", WORKDIR / "b.mp4", WORKDIR / "c.mp4"
    make_solid(src_a, "red", 1.0)
    make_solid(src_b, "green", 1.0)
    make_solid(src_c, "blue", 1.0)

    editor = Editor.create(WORKDIR / "demo.opm", fps=FPS, width=320, height=180)
    media_a = editor.import_media(src_a, kind="video")
    media_b = editor.import_media(src_b, kind="video")
    media_c = editor.import_media(src_c, kind="video")
    track = editor.add_track("video")

    clip_a = editor.add_clip(track.id, media_a.id, start=0, src_in=0, src_out=30)
    clip_b = editor.add_clip(track.id, media_b.id, start=clip_a.end, src_in=0, src_out=30)
    # add_transition shifts clip_b.start earlier to create the overlap - use
    # its *returned*, updated clip (not the pre-shift one) to place clip_c,
    # otherwise clip_c would be placed against clip_b's old end and leave an
    # undeclared gap where clip_b used to reach.
    clip_b = editor.add_transition(clip_b.id, "cross_dissolve", duration_frames=12)  # 0.4s dissolve A->B
    clip_c = editor.add_clip(track.id, media_c.id, start=clip_b.end, src_in=0, src_out=30)
    # B->C stays a hard cut.

    out = WORKDIR / "output.mp4"
    editor.export(out)

    result = probe(out)
    expected_duration = editor.project.timebase.frames_to_seconds(editor.duration_frames())
    print("--- ffprobe of exported file ---")
    print(f"duration_seconds:  {result.duration_seconds:.3f}")
    print(f"model duration:    {expected_duration:.3f} (30+30+30-12 frames)")

    checkpoints = {
        "frame_A_pure": 0.2,        # inside clip A, before dissolve
        "frame_dissolve_mid": 0.8,  # inside the A->B dissolve window
        "frame_B_pure": 1.1,        # past dissolve, pure B
        "frame_hardcut_before": 1.5,  # still B, just before the hard cut
        "frame_hardcut_after": 1.7,   # just past the hard cut into C
    }
    for name, t in checkpoints.items():
        extract_frame(out, t, WORKDIR / f"{name}.jpg")
    print(f"Frames written to {WORKDIR}")


if __name__ == "__main__":
    main()
