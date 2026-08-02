"""RunPod Queue worker for short text-to-video AnimateDiff clips."""

from __future__ import annotations

import base64
import os
import re
import secrets
import tempfile
import threading
from typing import Any

import imageio.v3 as iio
import numpy as np
import runpod
import torch
from diffusers import AnimateDiffSDXLPipeline, DDIMScheduler, MotionAdapter


MODELS = {
    "ponyDiffusionV6XL_v6StartWithThisOne.safetensors": os.getenv("MODEL_VIDEO_PONY", "AstraliteHeart/pony-diffusion-v6"),
    # Realistic Vision 5.1 is SD1.5; use its XL successor for this SDXL motion adapter.
    "realisticVisionV51_v51VAE.safetensors": os.getenv("MODEL_VIDEO_REALISTIC", "SG161222/RealVisXL_V4.0"),
    "juggernautXL_v9Rdphoto2Lightning.safetensors": os.getenv("MODEL_VIDEO_JUGGERNAUT", "RunDiffusion/Juggernaut-XL-v9"),
}
DEFAULT_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", MODELS["ponyDiffusionV6XL_v6StartWithThisOne.safetensors"])
MOTION_ADAPTER = os.getenv("MOTION_ADAPTER", "guoyww/animatediff-motion-adapter-sdxl-beta")
CACHE_DIR = os.getenv("HF_HOME", "/runpod-volume/huggingface")
MAX_PIXELS = int(os.getenv("MAX_VIDEO_PIXELS", str(1024 * 576)))
PROHIBITED = re.compile(
    r"\b(child|children|kid|minor|underage|loli|shota|preteen|young[- ]looking|"
    r"rape|raped|forced|coerc(?:e|ed|ion)|unconscious|drugged|non[- ]?consensual|"
    r"incest|bestiality)\b",
    re.IGNORECASE,
)

_lock = threading.Lock()
_pipe: Any = None
_model_id: str | None = None


def integer(value: Any, name: str, low: int, high: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("engine", "animatediff") != "animatediff":
        raise ValueError("only engine=animatediff is supported")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt or len(prompt) > 3000 or PROHIBITED.search(prompt):
        raise ValueError("invalid or prohibited prompt")
    width = integer(payload.get("width", 1024), "width", 256, 1024)
    height = integer(payload.get("height", 576), "height", 256, 1024)
    if width % 8 or height % 8 or width * height > MAX_PIXELS:
        raise ValueError("video dimensions exceed the endpoint limit")
    duration = integer(payload.get("duration_seconds", 3), "duration_seconds", 2, 5)
    fps = integer(payload.get("fps", 12), "fps", 4, 24)
    seed = int(payload.get("seed", -1))
    if seed < 0:
        seed = secrets.randbelow(2**31)
    requested = str(payload.get("model", ""))
    model_id = MODELS.get(requested, requested if "/" in requested else DEFAULT_MODEL)
    return {
        "prompt": prompt,
        "negative_prompt": str(payload.get("negative_prompt", ""))[:3000],
        "width": width,
        "height": height,
        "steps": integer(payload.get("steps", 24), "steps", 4, 40),
        "guidance": min(15.0, max(0.0, float(payload.get("cfg_scale", 7.0)))),
        "duration": duration,
        "fps": fps,
        "seed": seed,
        "model_id": model_id,
    }


def pipeline_for(model_id: str):
    global _pipe, _model_id
    if _pipe is not None and _model_id == model_id:
        return _pipe
    if _pipe is not None:
        del _pipe
        _pipe = None
        _model_id = None
        torch.cuda.empty_cache()
    token = os.getenv("HF_TOKEN") or None
    adapter = MotionAdapter.from_pretrained(MOTION_ADAPTER, cache_dir=CACHE_DIR, token=token, torch_dtype=torch.float16)
    pipe = AnimateDiffSDXLPipeline.from_pretrained(
        model_id,
        motion_adapter=adapter,
        cache_dir=CACHE_DIR,
        token=token,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config, clip_sample=False, timestep_spacing="linspace")
    pipe.enable_vae_slicing()
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    _pipe, _model_id = pipe, model_id
    return pipe


def resample(frames: list[Any], count: int) -> list[Any]:
    if len(frames) == count:
        return frames
    return [frames[round(i * (len(frames) - 1) / max(1, count - 1))] for i in range(count)]


def handler(job: dict[str, Any]) -> dict[str, Any]:
    values = validate(job.get("input") or {})
    model_id = values.pop("model_id")
    seed = values.pop("seed")
    duration, fps = values.pop("duration"), values.pop("fps")
    generated_count = min(24, max(8, duration * 4))
    with _lock, torch.inference_mode():
        pipe = pipeline_for(model_id)
        frames = pipe(
            prompt=values["prompt"],
            negative_prompt=values["negative_prompt"],
            width=values["width"],
            height=values["height"],
            num_frames=generated_count,
            num_inference_steps=values["steps"],
            guidance_scale=values["guidance"],
            generator=torch.Generator("cuda").manual_seed(seed),
        ).frames[0]
    frames = resample(frames, duration * fps)
    with tempfile.NamedTemporaryFile(suffix=".mp4") as output:
        video = np.stack([np.asarray(frame, dtype=np.uint8) for frame in frames])
        iio.imwrite(output.name, video, fps=fps, codec="libx264", quality=7, pixelformat="yuv420p")
        output.seek(0)
        encoded = base64.b64encode(output.read()).decode("ascii")
    return {"video": encoded, "content_type": "video/mp4", "seed": seed, "model": model_id}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
