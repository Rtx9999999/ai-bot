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

import requests
import runpod
import torch
from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image
from PIL import Image, ImageOps


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
_pipeline_kind: str | None = None
MAX_DOWNLOAD = int(os.getenv("MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024)))


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    input_image_url = str(payload.get("input_image_url", "")).strip()
    task = str(payload.get("task", "")).strip()
    if input_image_url and task != "outfit_change":
        raise ValueError("input_image_url is only supported for task=outfit_change")
    if task == "outfit_change" and (
        not input_image_url.startswith("https://")
        or payload.get("require_clothed_output") is not True
    ):
        raise ValueError("outfit_change requires an HTTPS image and clothed output")
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
        "input_image_url": input_image_url,
        "strength": min(0.85, max(0.2, float(payload.get("strength", 0.55)))),
    }


def pipeline_for(model_id: str, kind: str):
    global _pipeline, _loaded_model, _pipeline_kind
    if _pipeline is not None and _loaded_model == model_id and _pipeline_kind == kind:
        return _pipeline
    if _pipeline is not None:
        del _pipeline
        _pipeline = None
        _loaded_model = None
        _pipeline_kind = None
        gc.collect()
        torch.cuda.empty_cache()
    pipeline_class = AutoPipelineForImage2Image if kind == "img2img" else AutoPipelineForText2Image
    pipe = pipeline_class.from_pretrained(
        model_id,
        cache_dir=CACHE_DIR,
        token=os.getenv("HF_TOKEN") or None,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing()
    pipe.to("cuda")
    _pipeline, _loaded_model, _pipeline_kind = pipe, model_id, kind
    return pipe


def download_image(url: str, width: int, height: int) -> Image.Image:
    response = requests.get(url, timeout=(10, 90), stream=True)
    response.raise_for_status()
    length = int(response.headers.get("content-length", "0") or 0)
    if length > MAX_DOWNLOAD:
        raise ValueError("input image is too large")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(1024 * 1024):
        total += len(chunk)
        if total > MAX_DOWNLOAD:
            raise ValueError("input image is too large")
        chunks.append(chunk)
    image = Image.open(io.BytesIO(b"".join(chunks))).convert("RGB")
    return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)


def handler(job: dict[str, Any]) -> dict[str, Any]:
    try:
        values = validate(job.get("input") or {})
        with _lock, torch.inference_mode():
            input_url = values.pop("input_image_url")
            kind = "img2img" if input_url else "txt2img"
            pipe = pipeline_for(values.pop("model_id"), kind)
            seed = values.pop("seed")
            arguments = dict(
                prompt=values["prompt"],
                negative_prompt=values["negative_prompt"],
                width=values["width"],
                height=values["height"],
                num_inference_steps=values["steps"],
                guidance_scale=values["guidance"],
                generator=torch.Generator(device="cuda").manual_seed(seed),
            )
            if input_url:
                arguments["image"] = download_image(input_url, values["width"], values["height"])
                arguments["strength"] = values["strength"]
            image = pipe(**arguments).images[0]
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
