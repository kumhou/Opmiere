"""ComfyUIProvider — the local GPU generation backend (ARCHITECTURE.md 5.3/5.7).

Talks to a running ComfyUI server (default http://127.0.0.1:8188) over its
plain HTTP API: POST a node-graph workflow to /prompt, poll /history/{id},
fetch the result bytes via /view. Every graph below was verified by hand
against this machine's RTX 3070 before this file supported it:
  - image (SD1.5, 512x512, 20 steps): ~7s, ~2GB VRAM.
  - video (LTX-Video 2B distilled-fp8, 512x320, 65 frames/25fps, 30 steps):
    ~22s, ~6.4GB VRAM peak - comfortably inside the 8GB budget. Note LTX-2/
    LTX-2.3, the newer flagship model line, needs 16GB+ even quantized and
    was deliberately *not* used here; the original smaller LTX-Video line is
    still maintained and is the one actually suited to this hardware.
  - speech (Qwen3-TTS, 0.6B, Apache-2.0 — chosen over XTTS-v2/F5-TTS
    specifically because those are non-commercial-licensed and this one
    isn't): preset-voice generation uses the CustomVoice checkpoint; voice
    cloning needs the *separate* Base checkpoint (confirmed via a real
    "incompatible model" error before assuming otherwise) plus a reference
    clip's audio *and* its transcript — the node raises rather than
    guessing if either is missing.
  Every graph was traced from ComfyUI's own bundled example templates
  (litegraph UI format) and converted to the API format /prompt expects by
  hand, or built from the real node schemas via /object_info, rather than
  guessed from node names alone.

Scope note: the VRAM-adaptive quantization *profiles* from section 5.7
(auto-selecting GGUF/fp8/block-swap by detected VRAM) are follow-up work —
every kind here runs at whatever precision its downloaded checkpoint already
is, not further quantized; none of them have needed it yet on this 8GB card.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .provider import GenerationJob, GenerationProvider, JobStatus, ModelLicense

DEFAULT_IMAGE_CHECKPOINT = "v1-5-pruned-emaonly-fp16.safetensors"
DEFAULT_VIDEO_CHECKPOINT = "ltxv-2b-0.9.8-distilled-fp8.safetensors"
DEFAULT_VIDEO_TEXT_ENCODER = "t5xxl_fp8_e4m3fn_scaled.safetensors"
DEFAULT_SPEECH_CUSTOM_VOICE_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_SPEECH_CLONE_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_FLUX_SCHNELL_CHECKPOINT = "flux1-schnell-Q4_K_S.gguf"
DEFAULT_FLUX_DEV_CHECKPOINT = "flux1-dev-Q4_K_S.gguf"
FLUX_CLIP_L = "clip_l.safetensors"
FLUX_VAE = "ae.safetensors"
DEFAULT_WAN21_T2V_CHECKPOINT = "wan2.1_t2v_1.3B_fp16.safetensors"
WAN21_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
WAN21_VAE = "wan_2.1_vae.safetensors"
# Wan2.2's 14B T2V is a mixture-of-experts model shipped as two separate
# checkpoints (steps 0..split use HighNoise, split..end use LowNoise) - both
# named here since a job needs both to run, unlike every other model above
# which is a single file. Reuses Wan2.1's CLIP/VAE (same repo family).
DEFAULT_WAN22_HIGHNOISE_CHECKPOINT = "Wan2.2-T2V-A14B-HighNoise-Q4_K_S.gguf"
DEFAULT_WAN22_LOWNOISE_CHECKPOINT = "Wan2.2-T2V-A14B-LowNoise-Q4_K_S.gguf"
# Not a real filename - a synthetic key so the two-checkpoint MoE job still
# has exactly one CHECKPOINT_LICENSES entry to look up (both experts ship
# under the same Wan2.2 release/license, so one entry is accurate, not a
# simplification that loses information).
WAN22_MOE_LICENSE_KEY = "Wan2.2-T2V-A14B (HighNoise+LowNoise)"

# Which output node each workflow ends at, and which output dict key holds
# the result file list. image/video both really do use "images" (confirmed
# by reading SaveVideo's actual output, not assumed); speech's SaveAudio
# uses "audio" instead - a real, observed difference, not a typo.
_OUTPUT_NODE_BY_KIND = {"image": "9", "video": "79", "speech": "4"}
_OUTPUT_KEY_BY_KIND = {"image": "images", "video": "images", "speech": "audio"}

# Every checkpoint this provider knows how to load, and its real license -
# verified against the actual license text/terms page, not assumed from the
# model's reputation. Metadata only: flows into Media.origin (see
# ops.place_generated) so a project can be audited before commercial use: it
# never touches the generated pixels/audio themselves.
CHECKPOINT_LICENSES: dict[str, ModelLicense] = {
    DEFAULT_IMAGE_CHECKPOINT: ModelLicense(
        "CreativeML OpenRAIL-M", "yes",
        "Commercial use permitted, no revenue cap; use-based restrictions only "
        "(no illegal/harmful content)."),
    DEFAULT_VIDEO_CHECKPOINT: ModelLicense(
        "Lightricks Open Weights License", "conditional",
        "Free for commercial use only if your company's ARR is under $10M USD. "
        "Above that, requires a paid commercial license from Lightricks "
        "(ltxv-licensing@lightricks.com)."),
    DEFAULT_FLUX_SCHNELL_CHECKPOINT: ModelLicense(
        "Apache-2.0", "yes", "Fully permissive, no restrictions."),
    DEFAULT_FLUX_DEV_CHECKPOINT: ModelLicense(
        "FLUX.1-dev Non-Commercial License", "no",
        "Free for personal/research use only. Commercial use requires a separate "
        "license from Black Forest Labs."),
    DEFAULT_WAN21_T2V_CHECKPOINT: ModelLicense(
        "Apache-2.0", "yes", "Fully permissive, no restrictions."),
    WAN22_MOE_LICENSE_KEY: ModelLicense(
        "Apache-2.0", "yes", "Fully permissive, no restrictions."),
    DEFAULT_SPEECH_CUSTOM_VOICE_MODEL: ModelLicense(
        "Apache-2.0", "yes", "Fully permissive, no restrictions."),
    DEFAULT_SPEECH_CLONE_MODEL: ModelLicense(
        "Apache-2.0", "yes", "Fully permissive, no restrictions."),
}


class ComfyUIProvider(GenerationProvider):
    name = "comfyui"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        output_dir: Path | None = None,
        image_checkpoint: str = DEFAULT_IMAGE_CHECKPOINT,
        video_checkpoint: str = DEFAULT_VIDEO_CHECKPOINT,
        video_text_encoder: str = DEFAULT_VIDEO_TEXT_ENCODER,
        comfyui_input_dir: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / ".opmiere_generated"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_checkpoint = image_checkpoint
        self.video_checkpoint = video_checkpoint
        self.video_text_encoder = video_text_encoder
        # Voice cloning needs to hand ComfyUI a reference clip. ComfyUI's
        # LoadAudio node only accepts filenames already inside its own
        # input/ folder, so a machine-specific filesystem path is
        # unavoidable here - deliberately not hardcoded (this repo runs on
        # other people's machines too), read from an env var instead, with
        # a clear error at generation time if it's needed but unset.
        env_dir = os.environ.get("OPMIERE_COMFYUI_INPUT_DIR")
        self.comfyui_input_dir = Path(comfyui_input_dir) if comfyui_input_dir else (
            Path(env_dir) if env_dir else None
        )
        self.client_id = str(uuid.uuid4())
        # ComfyUI's /history doesn't echo back a plain-text "kind"/"prompt" in
        # an easily queryable form, so we remember our own request alongside
        # its job id rather than re-parsing the submitted graph back out.
        self._jobs: dict[str, dict[str, str]] = {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ComfyUI POST {path} failed: {e.code} {e.read().decode(errors='replace')}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"could not reach ComfyUI at {self.base_url} — is the server running?"
            ) from e

    def _get(self, path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}") as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"could not reach ComfyUI at {self.base_url} — is the server running?"
            ) from e

    def _build_txt2img_workflow(self, prompt: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        width = params.get("width", 512)
        height = params.get("height", 512)
        steps = params.get("steps", 20)
        cfg = params.get("cfg", 7.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get("negative_prompt", "blurry, low quality, watermark, text")
        checkpoint = params.get("checkpoint", self.image_checkpoint)
        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler",
                    "scheduler": "normal", "denoise": 1.0,
                    "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "opmiere_gen", "images": ["8", 0]}},
        }
        return workflow, checkpoint

    def _build_flux_workflow(self, prompt: str, params: dict[str, Any], model: str) -> tuple[dict[str, Any], str]:
        """Flux (schnell or dev) via GGUF. Both share the same graph shape,
        traced from ComfyUI's own bundled flux_schnell.json and
        flux_dev_checkpoint_example.json templates: only checkpoint and
        step count really differ (dev's own example also runs cfg=1, same
        as schnell - negative conditioning is moot either way, so a plain
        empty-string CLIPTextEncode is equivalent to dev's usual
        ConditioningZeroOut trick, not a shortcut that changes behavior).
        Verified against this RTX 3070 for schnell (Q4_K_S, 1024x1024,
        34s, ~7GB VRAM peak — dramatically better than SD1.5) before dev
        was wired in.
        """
        width = params.get("width", 1024)
        height = params.get("height", 1024)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get("negative_prompt", "")
        clip_name1 = params.get("clip_name1", FLUX_CLIP_L)
        clip_name2 = params.get("clip_name2", self.video_text_encoder)  # same t5xxl already used for LTX-Video
        vae_name = params.get("vae_name", FLUX_VAE)

        if model == "flux-schnell":
            checkpoint = params.get("checkpoint", DEFAULT_FLUX_SCHNELL_CHECKPOINT)
            steps = params.get("steps", 4)
        elif model == "flux-dev":
            checkpoint = params.get("checkpoint", DEFAULT_FLUX_DEV_CHECKPOINT)
            steps = params.get("steps", 20)
        else:
            raise ValueError(f"unknown flux model {model!r}; choices: flux-schnell, flux-dev")
        cfg = params.get("cfg", 1.0)

        workflow = {
            "30": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": checkpoint}},
            "31": {"class_type": "DualCLIPLoader", "inputs": {
                "clip_name1": clip_name1, "clip_name2": clip_name2, "type": "flux"}},
            "32": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["31", 0], "text": prompt}},
            "33": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["31", 0], "text": negative}},
            "27": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                "denoise": 1.0, "model": ["30", 0], "positive": ["6", 0], "negative": ["33", 0],
                "latent_image": ["27", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["32", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "opmiere_gen", "images": ["8", 0]}},
        }
        return workflow, checkpoint

    def _build_ltxv_workflow(self, prompt: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        width = params.get("width", 512)
        height = params.get("height", 320)
        num_frames = params.get("num_frames", 65)
        # Should match the target Opmiere project's timebase.fps (see
        # get_project_state) - import_media's fps-match check will reject a
        # mismatch at place_generated time rather than silently misplacing
        # frames, so this is worth getting right up front, not a guess.
        frame_rate = params.get("frame_rate", 25)
        steps = params.get("steps", 30)
        cfg = params.get("cfg", 3.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get(
            "negative_prompt",
            "low quality, worst quality, deformed, distorted, disfigured, motion smear, "
            "motion artifacts, fused fingers, bad anatomy, weird hand, ugly",
        )
        checkpoint = params.get("checkpoint", self.video_checkpoint)
        text_encoder = params.get("text_encoder", self.video_text_encoder)
        workflow = {
            "38": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": text_encoder, "type": "ltxv", "device": "default"}},
            "44": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": negative}},
            "70": {"class_type": "EmptyLTXVLatentVideo", "inputs": {
                "width": width, "height": height, "length": num_frames, "batch_size": 1}},
            "69": {"class_type": "LTXVConditioning", "inputs": {
                "positive": ["6", 0], "negative": ["7", 0], "frame_rate": frame_rate}},
            "73": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "71": {"class_type": "LTXVScheduler", "inputs": {
                "latent": ["70", 0], "steps": steps, "max_shift": 2.05, "base_shift": 0.95,
                "stretch": True, "terminal": 0.1}},
            "72": {"class_type": "SamplerCustom", "inputs": {
                "model": ["44", 0], "positive": ["69", 0], "negative": ["69", 1],
                "sampler": ["73", 0], "sigmas": ["71", 0], "latent_image": ["70", 0],
                "add_noise": True, "noise_seed": seed, "cfg": cfg}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["72", 0], "vae": ["44", 2]}},
            "78": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": frame_rate}},
            "79": {"class_type": "SaveVideo", "inputs": {
                "video": ["78", 0], "filename_prefix": "opmiere_gen_video", "format": "auto", "codec": "auto"}},
        }
        return workflow, checkpoint

    def _build_wan_workflow(self, prompt: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Wan2.1 T2V 1.3B - the quality-over-speed video option (vs. the
        LTX-Video 2B default): Apache-2.0, visibly sharper/more coherent
        output in side-by-side testing, but ~6x slower (139s vs 22s on this
        RTX 3070) and closer to the 8GB ceiling (~7.7GB peak vs ~6.4GB).
        Graph traced from ComfyUI's own bundled text_to_video_wan.json
        template; node ids 78/79 deliberately match _build_ltxv_workflow's
        CreateVideo/SaveVideo so _OUTPUT_NODE_BY_KIND["video"] stays a single
        constant regardless of which video model built the graph (same trick
        _build_flux_workflow uses for SaveImage="9").
        """
        width = params.get("width", 832)
        height = params.get("height", 480)
        num_frames = params.get("num_frames", 33)
        frame_rate = params.get("frame_rate", 16)
        steps = params.get("steps", 30)
        cfg = params.get("cfg", 6.0)
        shift = params.get("shift", 8.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get(
            "negative_prompt",
            "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
            "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，畸形的",
        )
        checkpoint = params.get("checkpoint", DEFAULT_WAN21_T2V_CHECKPOINT)
        clip_name = params.get("clip_name", WAN21_CLIP)
        vae_name = params.get("vae_name", WAN21_VAE)
        workflow = {
            "37": {"class_type": "UNETLoader", "inputs": {"unet_name": checkpoint, "weight_dtype": "default"}},
            "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_name, "type": "wan", "device": "default"}},
            "39": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": negative}},
            "40": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
                "width": width, "height": height, "length": num_frames, "batch_size": 1}},
            "48": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["37", 0], "shift": shift}},
            "3": {"class_type": "KSampler", "inputs": {
                "model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["40", 0],
                "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "uni_pc", "scheduler": "simple",
                "denoise": 1.0}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
            "78": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": frame_rate}},
            "79": {"class_type": "SaveVideo", "inputs": {
                "video": ["78", 0], "filename_prefix": "opmiere_gen_video", "format": "auto", "codec": "auto"}},
        }
        return workflow, checkpoint

    def _build_wan22_moe_workflow(self, prompt: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Wan2.2 T2V A14B - the offload-tier option: two ~8.75GB GGUF
        experts (17.5GB combined), neither of which fits this 8GB card
        alongside the other, let alone both at once. Deliberately *not*
        configuring any special offload mechanism - ComfyUI's own default
        model management already pages models in/out of VRAM as a workflow
        references more of them than fit, and real nvidia-smi sampling
        during testing confirmed it: usage oscillated between ~4GB and
        ~7.9GB rather than climbing to 17GB+, as the two experts were
        swapped in turn. Real result: 283s for a small 480x480/17-frame
        test (vs Wan2.1's 139s for a larger 832x480/33-frame one) - slower,
        as expected from swap I/O plus a bigger active model per stage, but
        the visibly best quality of the three video options tested.

        Two-stage KSamplerAdvanced hand-off (standard base/refiner
        pattern): HighNoise runs steps 0..split_step and hands its latent
        (with leftover noise) to LowNoise for split_step..steps. Simplified
        from ComfyUI's own bundled video_wan2_2_14B_t2v.json subgraph
        template, dropping its LoRA/turbo-mode toggle scaffolding (built
        for a 4-step lightning fast-path, not this quality-tier default).
        """
        width = params.get("width", 480)
        height = params.get("height", 480)
        num_frames = params.get("num_frames", 17)
        frame_rate = params.get("frame_rate", 16)
        steps = params.get("steps", 20)
        split_step = params.get("split_step", steps // 2)
        cfg = params.get("cfg", 3.5)
        shift = params.get("shift", 5.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get(
            "negative_prompt",
            "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
            "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，畸形的",
        )
        high_noise_checkpoint = params.get("high_noise_checkpoint", DEFAULT_WAN22_HIGHNOISE_CHECKPOINT)
        low_noise_checkpoint = params.get("low_noise_checkpoint", DEFAULT_WAN22_LOWNOISE_CHECKPOINT)
        clip_name = params.get("clip_name", WAN21_CLIP)
        vae_name = params.get("vae_name", WAN21_VAE)
        workflow = {
            "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip_name, "type": "wan", "device": "default"}},
            "39": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
            "75": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": high_noise_checkpoint}},
            "76": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": low_noise_checkpoint}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": negative}},
            "40": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
                "width": width, "height": height, "length": num_frames, "batch_size": 1}},
            "82": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["75", 0], "shift": shift}},
            "86": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["76", 0], "shift": shift}},
            "20": {"class_type": "KSamplerAdvanced", "inputs": {
                "model": ["82", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["40", 0],
                "add_noise": "enable", "noise_seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "simple",
                "start_at_step": 0, "end_at_step": split_step, "return_with_leftover_noise": "enable"}},
            "21": {"class_type": "KSamplerAdvanced", "inputs": {
                "model": ["86", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["20", 0],
                "add_noise": "disable", "noise_seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": "euler", "scheduler": "simple",
                "start_at_step": split_step, "end_at_step": 10000, "return_with_leftover_noise": "disable"}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["39", 0]}},
            "78": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": frame_rate}},
            "79": {"class_type": "SaveVideo", "inputs": {
                "video": ["78", 0], "filename_prefix": "opmiere_gen_video", "format": "auto", "codec": "auto"}},
        }
        return workflow, WAN22_MOE_LICENSE_KEY

    def _build_speech_workflow(self, prompt: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        language = params.get("language", "Auto")
        reference_audio = params.get("reference_audio")
        reference_text = params.get("reference_text")

        if reference_audio:
            # Voice cloning: needs the *Base* checkpoint - not CustomVoice,
            # confirmed by ComfyUI's own "incompatible model" error the
            # first time this was tried with the wrong one - plus both the
            # reference clip's audio and its transcript.
            if not reference_text:
                raise ValueError(
                    "kind='speech' with reference_audio also requires reference_text "
                    "(its transcript) - Qwen3-TTS's own voice-clone node requires both"
                )
            if self.comfyui_input_dir is None:
                raise ValueError(
                    "voice cloning needs a reference clip uploaded into ComfyUI's own "
                    "input/ folder, but comfyui_input_dir isn't configured - pass it to "
                    "ComfyUIProvider() or set the OPMIERE_COMFYUI_INPUT_DIR env var"
                )
            src = Path(reference_audio)
            if not src.exists():
                raise FileNotFoundError(f"reference_audio not found: {src}")
            dest_name = f"opmiere_ref_{uuid.uuid4().hex[:8]}{src.suffix}"
            shutil.copy2(src, self.comfyui_input_dir / dest_name)
            checkpoint = params.get("checkpoint", DEFAULT_SPEECH_CLONE_MODEL)
            workflow = {
                "1": {"class_type": "Qwen3Loader", "inputs": {
                    "repo_id": checkpoint, "source": "HuggingFace", "precision": "bf16", "attention": "auto"}},
                "2": {"class_type": "LoadAudio", "inputs": {"audio": dest_name}},
                "3": {"class_type": "Qwen3VoiceClone", "inputs": {
                    "model": ["1", 0], "text": prompt, "seed": seed, "language": language,
                    "ref_audio": ["2", 0], "ref_text": reference_text}},
                "4": {"class_type": "SaveAudio", "inputs": {"audio": ["3", 0], "filename_prefix": "opmiere_gen_speech"}},
            }
            return workflow, checkpoint

        # No reference clip: a preset speaker via the CustomVoice checkpoint.
        speaker = params.get("speaker", "Vivian")
        checkpoint = params.get("checkpoint", DEFAULT_SPEECH_CUSTOM_VOICE_MODEL)
        workflow = {
            "1": {"class_type": "Qwen3Loader", "inputs": {
                "repo_id": checkpoint, "source": "HuggingFace", "precision": "bf16", "attention": "auto"}},
            "2": {"class_type": "Qwen3CustomVoice", "inputs": {
                "model": ["1", 0], "text": prompt, "language": language, "speaker": speaker, "seed": seed}},
            "4": {"class_type": "SaveAudio", "inputs": {"audio": ["2", 0], "filename_prefix": "opmiere_gen_speech"}},
        }
        return workflow, checkpoint

    def submit(self, kind: str, prompt: str, params: dict[str, Any]) -> str:
        if kind == "image":
            model = params.get("model", "sd1.5")
            if model == "sd1.5":
                workflow, checkpoint = self._build_txt2img_workflow(prompt, params)
            elif model in ("flux-schnell", "flux-dev"):
                workflow, checkpoint = self._build_flux_workflow(prompt, params, model)
            else:
                raise ValueError(f"unknown image model {model!r}; choices: sd1.5, flux-schnell, flux-dev")
        elif kind == "video":
            video_model = params.get("model", "ltx-video")
            if video_model == "ltx-video":
                workflow, checkpoint = self._build_ltxv_workflow(prompt, params)
            elif video_model == "wan2.1":
                workflow, checkpoint = self._build_wan_workflow(prompt, params)
            elif video_model == "wan2.2-moe":
                workflow, checkpoint = self._build_wan22_moe_workflow(prompt, params)
            else:
                raise ValueError(
                    f"unknown video model {video_model!r}; choices: ltx-video, wan2.1, wan2.2-moe")
        elif kind == "speech":
            workflow, checkpoint = self._build_speech_workflow(prompt, params)
        else:
            raise NotImplementedError(
                f"ComfyUIProvider does not support kind={kind!r} yet "
                "(sfx/music generation are follow-up work)"
            )
        resp = self._post("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if resp.get("node_errors"):
            raise ValueError(f"ComfyUI rejected the workflow: {resp['node_errors']}")
        job_id = resp["prompt_id"]
        self._jobs[job_id] = {"kind": kind, "prompt": prompt, "checkpoint": checkpoint}
        return job_id

    def status(self, job_id: str) -> GenerationJob:
        if job_id not in self._jobs:
            raise KeyError(f"unknown job id {job_id!r} (not submitted through this provider instance)")
        meta = self._jobs[job_id]
        history = self._get(f"/history/{job_id}")

        if job_id not in history:
            # Not in history yet: ComfyUI doesn't distinguish "still queued"
            # from "actively running" through this simple endpoint, so both
            # report as RUNNING here - the caller's action (keep polling) is
            # the same either way. See provider.py's JobStatus for the
            # documented vocabulary.
            return GenerationJob(id=job_id, status=JobStatus.RUNNING, kind=meta["kind"], prompt=meta["prompt"])

        entry = history[job_id]
        status_str = entry.get("status", {}).get("status_str")
        if status_str != "success":
            messages = entry.get("status", {}).get("messages", [])
            return GenerationJob(
                id=job_id, status=JobStatus.ERROR, kind=meta["kind"], prompt=meta["prompt"],
                error=f"ComfyUI job did not succeed (status_str={status_str!r}): {messages}",
            )

        output_node = _OUTPUT_NODE_BY_KIND.get(meta["kind"])
        output_key = _OUTPUT_KEY_BY_KIND.get(meta["kind"])
        files = (
            entry.get("outputs", {}).get(output_node, {}).get(output_key, [])
            if output_node and output_key else []
        )
        if not files:
            return GenerationJob(
                id=job_id, status=JobStatus.ERROR, kind=meta["kind"], prompt=meta["prompt"],
                error=f"ComfyUI reported success but produced no output on node {output_node!r}",
            )
        img = files[0]
        url = (
            f"{self.base_url}/view?filename={img['filename']}"
            f"&subfolder={img.get('subfolder', '')}&type={img['type']}"
        )
        dest = self.output_dir / f"{job_id}_{img['filename']}"
        try:
            urllib.request.urlretrieve(url, dest)
        except urllib.error.URLError as e:
            raise ConnectionError(f"could not fetch generated result from ComfyUI: {e}") from e

        return GenerationJob(
            id=job_id, status=JobStatus.DONE, kind=meta["kind"], prompt=meta["prompt"], result_path=dest,
            license=CHECKPOINT_LICENSES.get(meta["checkpoint"]),
        )

    def wait(self, job_id: str, timeout_seconds: float = 180.0, poll_interval: float = 1.0) -> GenerationJob:
        """Convenience for scripts/tests: block until DONE or ERROR. The
        async job model (submit + poll status) remains the real API surface
        an agent uses via MCP; this just saves callers from writing their
        own poll loop when synchronous waiting is genuinely what they want.
        """
        deadline = time.time() + timeout_seconds
        while True:
            job = self.status(job_id)
            if job.status in (JobStatus.DONE, JobStatus.ERROR):
                return job
            if time.time() > deadline:
                raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds}s")
            time.sleep(poll_interval)
