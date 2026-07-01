"""P1.5 proof: color + fade effects actually change the rendered pixels.

Builds a single clip with a strong color grade and a fade-in/fade-out, exports
it, and extracts three frames (start / middle / end) so the effect can be
looked at directly rather than inferred from "no exception was raised".

Run:  python examples/p1_5_effects_demo.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opmiere import Editor  # noqa: E402
from opmiere.render import probe  # noqa: E402

WORKDIR = Path(__file__).resolve().parent / "_p1_5_run"
FPS = 30
SECONDS = 3


def make_sample(path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=480x270:rate={FPS}:duration={SECONDS}",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=" + str(SECONDS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def extract_frame(video_path: Path, at_seconds: float, out_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video_path),
           "-frames:v", "1", "-q:v", "3", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    src = WORKDIR / "source.mp4"
    make_sample(src)

    editor = Editor.create(WORKDIR / "demo.opm", fps=FPS, width=480, height=270)
    media = editor.import_media(src, kind="video")
    track = editor.add_track("video")
    n = editor.project.timebase.seconds_to_frames(SECONDS)
    clip = editor.add_clip(track.id, media.id, start=0, src_in=0, src_out=n)

    # Strong, unmistakable-in-a-screenshot color grade.
    editor.apply_effect(clip.id, {"type": "color", "saturation": 0.0, "contrast": 1.4, "brightness": 0.05})
    # 1s fade in, 1s fade out on a 3s clip.
    editor.apply_effect(clip.id, {"type": "fade", "direction": "in", "duration_frames": FPS})
    editor.apply_effect(clip.id, {"type": "fade", "direction": "out", "duration_frames": FPS})

    out = WORKDIR / "output.mp4"
    editor.export(out)

    result = probe(out)
    print("--- ffprobe of exported file ---")
    print(f"duration_seconds: {result.duration_seconds:.3f}")
    print(f"resolution:       {result.width}x{result.height}")

    extract_frame(out, 0.1, WORKDIR / "frame_start.jpg")   # inside fade-in -> should be near black
    extract_frame(out, 1.5, WORKDIR / "frame_mid.jpg")     # full effect -> grayscale + higher contrast
    extract_frame(out, 2.9, WORKDIR / "frame_end.jpg")     # inside fade-out -> should be near black
    print(f"Frames written to {WORKDIR}")


if __name__ == "__main__":
    main()
