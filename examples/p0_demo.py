"""P0 headless proof: project model -> .opm bundle -> real exported mp4.

No GUI, no generation — just the engine path. Synthesizes two short, visually
distinct test clips with ffmpeg's lavfi test sources (so the concat cut point
is independently verifiable), builds a project, imports them, places them
back-to-back with an in/out trim on each, and exports a real file.

Run:  python examples/p0_demo.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from opmiere import Bundle, Project  # noqa: E402
from opmiere.render import FFmpegBackend, import_media, probe  # noqa: E402

FPS = 30
WORKDIR = Path(__file__).resolve().parent / "_p0_run"


def make_test_source(path: Path, pattern: str, freq: int, seconds: float) -> None:
    """A short synthetic clip: a moving test pattern + an audible sine tone."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"{pattern}=size=640x360:rate={FPS}:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to synthesize {path}:\n{proc.stderr}")


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    src_a = WORKDIR / "source_a.mp4"
    src_b = WORKDIR / "source_b.mp4"
    print("Synthesizing test sources (testsrc2 @440Hz, smptebars @220Hz)...")
    make_test_source(src_a, "testsrc2", 440, seconds=3)
    make_test_source(src_b, "smptebars", 220, seconds=3)

    project = Project()
    project.timebase.fps = FPS
    project.resolution.w, project.resolution.h = 640, 360

    bundle = Bundle.create(WORKDIR / "demo.opm", project=project)

    media_a = import_media(bundle, project, src_a, kind="video")
    media_b = import_media(bundle, project, src_b, kind="video")
    print(f"Imported {media_a.id} ({media_a.duration_frames}f) and "
          f"{media_b.id} ({media_b.duration_frames}f)")

    video_track = project.add_track("video")
    # First 2s (frames 0-60) of A, then 1s (frames 0-30) of B, back-to-back.
    clip_a = project.add_clip(video_track, media_a, start=0, src_in=0, src_out=60)
    project.add_clip(video_track, media_b, start=clip_a.end, src_in=0, src_out=30)

    bundle.save(project)
    print(f"Bundle saved: {bundle.root}")
    print(f"Timeline duration: {project.duration_frames()} frames "
          f"({project.timebase.frames_to_seconds(project.duration_frames()):.2f}s)")

    output_path = WORKDIR / "output.mp4"
    print("Exporting...")
    FFmpegBackend().export(project, bundle, output_path)

    result = probe(output_path)
    print("\n--- ffprobe of exported file (ground truth, not claimed) ---")
    print(f"path:            {output_path}")
    print(f"duration_seconds:{result.duration_seconds:.3f}")
    print(f"fps:             {result.fps}")
    print(f"resolution:      {result.width}x{result.height}")
    print(f"has_video:       {result.has_video}")
    print(f"has_audio:       {result.has_audio}")


if __name__ == "__main__":
    main()
