"""quality_check: free, deterministic checks a generated (or imported) media
file can pass before anything gets an agent's expensive attention.

ARCHITECTURE.md 5.10's agent-director loop needs a cheap first gate - most
generation failures (a static frame passed off as "motion", silence where
narration should be, a solid black clip, an out-of-focus render) are
detectable with plain ffmpeg filters, no model call and no pixels sent to an
LLM. This is that gate. Real thresholds, not guessed: verified against actual
sharp vs. gblur=sigma=20 output (blur mean ~4.85 vs ~44.76) and real
black/frozen/silent clips before picking defaults.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .probe import probe, require_ffmpeg_tools

_BLACK_RE = re.compile(r"black_duration:([\d.]+)")
_FREEZE_RE = re.compile(r"freeze_start:\s*([\d.]+)")
_BLUR_RE = re.compile(r"blur mean:\s*(nan|[\d.]+)")
_SILENCE_RE = re.compile(r"silence_duration:\s*([\d.]+)")


@dataclass
class QualityCheckResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    is_black: bool = False
    is_static: bool = False
    is_blurry: bool | None = False  # None: blur couldn't be measured (e.g. a black clip)
    is_silent: bool | None = False  # None: no audio stream to check
    blur_score: float | None = None  # ffmpeg's own scale: higher = blurrier

    def to_dict(self) -> dict:
        return {
            "passed": self.passed, "issues": self.issues, "is_black": self.is_black,
            "is_static": self.is_static, "is_blurry": self.is_blurry, "is_silent": self.is_silent,
            "blur_score": self.blur_score,
        }


def quality_check(
    path: Path,
    *,
    black_ratio_threshold: float = 0.9,
    silence_ratio_threshold: float = 0.9,
    blur_threshold: float = 30.0,
    silence_noise_db: float = -50.0,
) -> QualityCheckResult:
    """Run the free checks and report what's wrong, if anything.

    Thresholds are ratios of the clip's own duration (e.g. black_ratio_threshold=0.9
    means "at least 90% of the clip is black"), so this scales to clips of any
    length rather than a fixed-seconds cutoff that would misfire on short generated
    fragments. blur_threshold is on ffmpeg's own blurdetect scale (not 0-1 despite
    the filter's internal high/low options being 0-1) - 30 sits between a verified
    sharp sample (~4.85) and a heavily blurred one (~44.76).
    """
    require_ffmpeg_tools()
    path = Path(path)
    info = probe(path)
    duration = info.duration_seconds
    # freezedetect/blackdetect/silencedetect all default their own minimum
    # "sustained" duration to 2s, which would silently detect nothing on a
    # typical short generated clip - scale it down instead of using a fixed
    # small number that could false-positive on brief legitimate cuts.
    min_d = max(0.05, min(0.5, duration * 0.2))

    args = ["ffmpeg", "-i", str(path)]
    if info.has_video:
        args += ["-vf", f"blackdetect=d={min_d}:pic_th=0.98,freezedetect=n=0.001:d={min_d},blurdetect"]
    if info.has_audio:
        args += ["-af", f"silencedetect=n={silence_noise_db}dB:d={min_d}"]
    args += ["-f", "null", "-"]
    proc = subprocess.run(args, capture_output=True, text=True)
    log = proc.stderr

    result = QualityCheckResult(passed=True, is_blurry=None if not info.has_video else False,
                                 is_silent=None if not info.has_audio else False)

    if info.has_video:
        black_total = sum(float(m) for m in _BLACK_RE.findall(log))
        if duration > 0 and black_total / duration >= black_ratio_threshold:
            result.is_black = True
            result.issues.append(f"black for {black_total:.1f}s of {duration:.1f}s")

        if _FREEZE_RE.search(log):
            result.is_static = True
            result.issues.append("frozen/static picture detected")

        blur_matches = _BLUR_RE.findall(log)
        if blur_matches:
            # Multiple blackdetect/freezedetect/blurdetect instances can each
            # log once; blurdetect logs one "blur mean" per completed frame
            # window - the last one reflects the whole clip.
            last = blur_matches[-1]
            if last != "nan":
                score = float(last)
                result.blur_score = score
                result.is_blurry = score > blur_threshold
                if result.is_blurry:
                    result.issues.append(f"blurry (score {score:.1f} > {blur_threshold})")

    if info.has_audio:
        silence_total = sum(float(m) for m in _SILENCE_RE.findall(log))
        if duration > 0 and silence_total / duration >= silence_ratio_threshold:
            result.is_silent = True
            result.issues.append(f"silent for {silence_total:.1f}s of {duration:.1f}s")

    result.passed = not result.issues
    return result
