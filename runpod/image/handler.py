"""RunPod Queue worker matching the Telegram bot text-to-image contract."""

from __future__ import annotations

import base64
import gc
import io
import os
import re
import secrets
import threading
from typing import Any

import runpod
import torch
from diffusers import AutoPipelineForText2Image


MODEL_IDS = {
    "ponyDiffusionV6XL_v6StartWithThisOne.safetensors": os.getenv("MODEL_PONY", "AstraliteHeart/pony-diffusion-v6"),
    "realisticVisionV51_v51VAE.safetensors": os.getenv("MODEL_REALISTIC", "SG161222/Realistic_Vision_V5.1_noVAE"),
    "juggernautXL_v9Rdphoto2Lightning.safetensors": os.getenv("MODEL_JUGGERNAUT", "RunDiffusion/Juggernaut-XL-v9"),
}
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", MODEL_IDS["ponyDiffusionV6XL_v6StartWithThisOne.safetensors"])
CACHE_DIR = os.getenv("HF_HOME", "/runpod-volume/huggingface")
MAX_PIXELS = int(os.getenv("MAX_PIXELS", str(1024 * 1024)))
PROHIBITED = re.compile(
    r"\b(child|children|kid|minor|underage|loli|shota|preteen|young[- ]looking|"
    r"rape|raped|forced|coerc(?:e|ed|ion)|unconscious|drugged|non[- ]?consensual|"
    r"incest|bestiality)\b",
    re.IGNORECASE,
)

_lock = threading.Lock()
_pipeline: Any = None
_loaded_model: str | None = None


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("input_image_url") or payload.get("task"):
        raise ValueError("this endpoint supports text-to-image jobs only")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt or len(prompt) > 3000:
        raise ValueError("prompt is required and must not exceed 3000 characters")
    if PROHIBITED.search(prompt):
        raise ValueError("prompt violates the endpoint safety policy")
    width = _integer(payload.get("width", 1024), "width", 256, 1536)
    height = _integer(payload.get("height", 1024), "height", 256, 1536)
    if width % 8 or height % 8 or width * height > MAX_PIXELS:
        raise ValueError("dimensions must be multiples of 8 and at most MAX_PIXELS")
    steps = _integer(payload.get("steps", 30), "steps", 1, 60)
    guidance = float(payload.get("cfg_scale", 7.0))
    if not 0 <= guidance <= 20:
        raise ValueError("cfg_scale must be between 0 and 20")
    seed = int(payload.get("seed", -1))
    if seed < 0:
        seed = secrets.randbelow(2**31)
    requested = str(payload.get("model", "")).strip()
    model_id = MODEL_IDS.get(requested, requested if "/" in requested else DEFAULT_MODEL)
    return {
        "prompt": prompt,
        "negative_prompt": str(payload.get("negative_prompt", ""))[:3000],
        "width": width,
        "height": height,
        "steps": steps,
        "guidance": guidance,
        "seed": seed,
        "model_id": model_id,
    }


def pipeline_for(model_id: str):
    global _pipeline, _loaded_model
    if _pipeline is not None and _loaded_model == model_id:
        return _pipeline
    if _pipeline is not None:
        del _pipeline
        _pipeline = None
        _loaded_model = None
        gc.collect()
        torch.cuda.empty_cache()
    pipe = AutoPipelineForText2Image.from_pretrained(
        model_id,
        cache_dir=CACHE_DIR,
        token=os.getenv("HF_TOKEN") or None,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing()
    pipe.to("cuda")
    _pipeline = pipe
    _loaded_model = model_id
    return pipe


def handler(job: dict[str, Any]) -> dict[str, Any]:
    try:
        values = validate(job.get("input") or {})
        with _lock, torch.inference_mode():
            pipe = pipeline_for(values.pop("model_id"))
            seed = values.pop("seed")
            image = pipe(
                prompt=values["prompt"],
                negative_prompt=values["negative_prompt"],
                width=values["width"],
                height=values["height"],
                num_inference_steps=values["steps"],
                guidance_scale=values["guidance"],
                generator=torch.Generator(device="cuda").manual_seed(seed),
            ).images[0]
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return {
            "image": base64.b64encode(output.getvalue()).decode("ascii"),
            "content_type": "image/png",
            "seed": seed,
            "model": _loaded_model,
        }
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
