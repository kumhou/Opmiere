"""VRAM-adaptive generation profiles (ARCHITECTURE.md 5.7) - the auto
recommendation layer JH asked for: "根据硬件能力的不同推荐不同的模型",
split into two tracks, non-offload and offload, rather than one single
"best pick per VRAM tier" table.

Every number here is a real measurement taken on the reference RTX 3070
(8GB) this session, not a spec-sheet guess (see ARCHITECTURE.md section 9
for the full comparison writeup). Recommending for a different card just
means comparing these same peaks against a different detected vram_gb -
the profiles themselves don't change until they're re-measured on other
hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["draft", "balanced", "max"]
_TIER_RANK: dict[Tier, int] = {"draft": 0, "balanced": 1, "max": 2}


@dataclass(frozen=True)
class GenerationProfile:
    model: str
    tier: Tier
    offload: bool
    # Observed peak VRAM (GB, absolute nvidia-smi reading including OS/
    # desktop baseline) for non-offload profiles - the number a candidate
    # must fit under. For offload profiles this is the *combined* weight
    # size instead (doesn't need to fit; informational only).
    vram_gb: float
    seconds: float  # observed wall-clock for the real test run, informational
    notes: str

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model, "tier": self.tier, "offload": self.offload,
            "vram_gb": self.vram_gb, "seconds": self.seconds, "notes": self.notes,
        }


GENERATION_PROFILES: dict[str, list[GenerationProfile]] = {
    "image": [
        GenerationProfile(
            "sd1.5", "draft", False, 2.0, 7,
            "512x512, 20 steps. CreativeML OpenRAIL-M, commercial-safe."),
        GenerationProfile(
            "flux-schnell", "balanced", False, 7.0, 34,
            "1024x1024, 4 steps, GGUF Q4_K_S. Apache-2.0, commercial-safe. "
            "Dramatically sharper than sd1.5 for +27s."),
        GenerationProfile(
            "flux-dev", "max", False, 7.0, 82,
            "1024x1024, 20 steps, GGUF Q4_K_S. FLUX.1-dev Non-Commercial "
            "License - check get_license_report() before shipping."),
    ],
    "video": [
        GenerationProfile(
            "ltx-video", "draft", False, 6.4, 22,
            "512x320, 65 frames/25fps, 30 steps. Lightricks Open Weights "
            "License - commercial-safe only under $10M company ARR."),
        GenerationProfile(
            "wan2.1", "balanced", False, 7.7, 139,
            "832x480, 33 frames/16fps, 30 steps. Apache-2.0, commercial-safe. "
            "Visibly sharper/more coherent than ltx-video, ~6x slower."),
        GenerationProfile(
            "wan2.2-moe", "max", True, 17.5, 283,
            "480x480, 17 frames/16fps, 20 steps (small first test - scales "
            "up for real use). Two 8.75GB GGUF experts ComfyUI pages "
            "in/out automatically (confirmed via nvidia-smi: usage "
            "oscillates ~4-8GB, never holds both). Apache-2.0, "
            "commercial-safe. Best quality of the three, slowest."),
    ],
    "speech": [
        GenerationProfile(
            "qwen3-tts", "balanced", False, 2.0, 5,
            "Preset voice or reference-clip cloning. Apache-2.0, "
            "commercial-safe."),
    ],
}


def recommend(kind: str, vram_gb: float, offload: bool = False) -> GenerationProfile:
    """Pick the best profile for `kind` given detected VRAM and whether
    offload is acceptable. No I/O - callers own detecting vram_gb (see
    ComfyUIProvider.detect_vram_gb) so this stays trivially testable.

    non-offload: the highest tier whose known peak fits under vram_gb, no
    extra safety margin - each vram_gb here is already a real absolute
    nvidia-smi peak (OS/desktop baseline included), so shaving off more on
    top would just exclude proven-working setups. Concretely: wan2.1 (7.7GB
    peak) genuinely completed on the 8.0GB reference card it was measured
    on, and a margin here previously excluded it - wrong, and contrary to
    JH's explicit stance that a tight fit is fine, quality is what matters.
    Falls back to the smallest/cheapest profile if nothing fits rather than
    raising, since draft-tier is always worth attempting.

    offload: doesn't need to fit by definition - always returns the
    highest tier available in that track.
    """
    candidates = [p for p in GENERATION_PROFILES.get(kind, []) if p.offload == offload]
    if not candidates:
        raise ValueError(
            f"no {'offload' if offload else 'non-offload'} generation profile known for kind={kind!r}"
        )
    if offload:
        return max(candidates, key=lambda p: _TIER_RANK[p.tier])
    fitting = [p for p in candidates if p.vram_gb <= vram_gb]
    if fitting:
        return max(fitting, key=lambda p: _TIER_RANK[p.tier])
    return min(candidates, key=lambda p: p.vram_gb)
