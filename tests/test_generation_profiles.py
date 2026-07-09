"""Tests for the VRAM-adaptive generation-profiles recommendation logic
(ARCHITECTURE.md 5.7). Pure function, no network/server - see
test_comfyui_provider.py for detect_vram_gb()/recommend_profile()'s thin
HTTP-calling wrapper around this.
"""

import pytest

from opmiere.generation.profiles import GENERATION_PROFILES, recommend


def test_recommend_non_offload_picks_max_tier_that_fits_reference_card():
    profile = recommend("image", vram_gb=8.0, offload=False)

    assert profile.model == "flux-dev"
    assert profile.tier == "max"


def test_recommend_non_offload_video_picks_wan21_on_the_exact_reference_card():
    # wan2.1's measured peak (7.7GB) genuinely completed on the 8.0GB card
    # it was tested on - a prior version of this function applied a 10%
    # safety margin that wrongly excluded it. No margin: use the real
    # measured peak as-is.
    profile = recommend("video", vram_gb=8.0, offload=False)

    assert profile.model == "wan2.1"


def test_recommend_non_offload_picks_lower_tier_on_a_smaller_card():
    profile = recommend("image", vram_gb=3.0, offload=False)

    assert profile.model == "sd1.5"
    assert profile.tier == "draft"


def test_recommend_non_offload_falls_back_to_smallest_when_nothing_fits():
    profile = recommend("image", vram_gb=1.0, offload=False)

    assert profile.model == "sd1.5"


def test_recommend_offload_ignores_vram_and_returns_max_tier():
    profile = recommend("video", vram_gb=1.0, offload=True)

    assert profile.model == "wan2.2-moe"
    assert profile.offload is True


def test_recommend_offload_raises_when_no_offload_profile_exists():
    with pytest.raises(ValueError, match="offload"):
        recommend("image", vram_gb=8.0, offload=True)


def test_recommend_rejects_unknown_kind():
    with pytest.raises(ValueError, match="no .* generation profile"):
        recommend("not-a-kind", vram_gb=8.0, offload=False)


def test_recommend_music_picks_ace_step():
    profile = recommend("music", vram_gb=8.0, offload=False)

    assert profile.model == "ace-step"


def test_recommend_sfx_picks_stable_audio_open():
    profile = recommend("sfx", vram_gb=8.0, offload=False)

    assert profile.model == "stable-audio-open"
    assert profile.offload is False


def test_every_profile_serializes_to_dict():
    for profiles in GENERATION_PROFILES.values():
        for profile in profiles:
            d = profile.to_dict()
            assert d["model"] == profile.model
            assert d["tier"] in ("draft", "balanced", "max")
