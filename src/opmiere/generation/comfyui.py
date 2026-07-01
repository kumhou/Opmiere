"""ComfyUIProvider — the local GPU generation backend (ARCHITECTURE.md 5.3/5.7).

Talks to a running ComfyUI server (default http://127.0.0.1:8188) over its
plain HTTP API: POST a node-graph workflow to /prompt, poll /history/{id},
fetch the result bytes via /view. Both graphs below were verified by hand
against this machine's RTX 3070 before this file supported them:
  - image (SD1.5, 512x512, 20 steps): ~7s, ~2GB VRAM.
  - video (LTX-Video 2B distilled-fp8, 512x320, 65 frames/25fps, 30 steps):
    ~22s, ~6.4GB VRAM peak - comfortably inside the 8GB budget. Note LTX-2/
    LTX-2.3, the newer flagship model line, needs 16GB+ even quantized and
    was deliberately *not* used here; the original smaller LTX-Video line is
    still maintained and is the one actually suited to this hardware.
  The video graph was traced from ComfyUI's own bundled
  ltxv_text_to_video.json template (litegraph UI format) and converted to
  the API format /prompt expects by hand, rather than guessed from node
  names alone.

Scope note: audio generation and the VRAM-adaptive quantization *profiles*
from section 5.7 (auto-selecting GGUF/fp8/block-swap by detected VRAM) are
follow-up work — image and video both currently run at whatever precision
their downloaded checkpoint already is (fp16/fp8), not further quantized.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .provider import GenerationJob, GenerationProvider, JobStatus

DEFAULT_IMAGE_CHECKPOINT = "v1-5-pruned-emaonly-fp16.safetensors"
DEFAULT_VIDEO_CHECKPOINT = "ltxv-2b-0.9.8-distilled-fp8.safetensors"
DEFAULT_VIDEO_TEXT_ENCODER = "t5xxl_fp8_e4m3fn_scaled.safetensors"

# Which output node each workflow ends at, and which output key holds the
# result file list - both graphs happen to use "images" for that key (yes,
# even the video one - that's ComfyUI's real, observed SaveVideo output
# schema, not a naming choice made here).
_OUTPUT_NODE_BY_KIND = {"image": "9", "video": "79"}


class ComfyUIProvider(GenerationProvider):
    name = "comfyui"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        output_dir: Path | None = None,
        image_checkpoint: str = DEFAULT_IMAGE_CHECKPOINT,
        video_checkpoint: str = DEFAULT_VIDEO_CHECKPOINT,
        video_text_encoder: str = DEFAULT_VIDEO_TEXT_ENCODER,
    ):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / ".opmiere_generated"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.image_checkpoint = image_checkpoint
        self.video_checkpoint = video_checkpoint
        self.video_text_encoder = video_text_encoder
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

    def _build_txt2img_workflow(self, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        width = params.get("width", 512)
        height = params.get("height", 512)
        steps = params.get("steps", 20)
        cfg = params.get("cfg", 7.0)
        seed = params.get("seed", random.randint(0, 2**31 - 1))
        negative = params.get("negative_prompt", "blurry, low quality, watermark, text")
        checkpoint = params.get("checkpoint", self.image_checkpoint)
        return {
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

    def _build_ltxv_workflow(self, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
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
        return {
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

    def submit(self, kind: str, prompt: str, params: dict[str, Any]) -> str:
        if kind == "image":
            workflow = self._build_txt2img_workflow(prompt, params)
        elif kind == "video":
            workflow = self._build_ltxv_workflow(prompt, params)
        else:
            raise NotImplementedError(
                f"ComfyUIProvider does not support kind={kind!r} yet "
                "(audio generation is follow-up work)"
            )
        resp = self._post("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if resp.get("node_errors"):
            raise ValueError(f"ComfyUI rejected the workflow: {resp['node_errors']}")
        job_id = resp["prompt_id"]
        self._jobs[job_id] = {"kind": kind, "prompt": prompt}
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
        images = entry.get("outputs", {}).get(output_node, {}).get("images", []) if output_node else []
        if not images:
            return GenerationJob(
                id=job_id, status=JobStatus.ERROR, kind=meta["kind"], prompt=meta["prompt"],
                error=f"ComfyUI reported success but produced no output on node {output_node!r}",
            )
        img = images[0]
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
