"""Consent-gated InsightFace face swap worker for images and short videos."""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
import runpod
from huggingface_hub import hf_hub_download
from insightface.app import FaceAnalysis
from insightface.model_zoo import get_model


MAX_DOWNLOAD = int(os.getenv("MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_VIDEO_SECONDS = float(os.getenv("MAX_VIDEO_SECONDS", "8"))
HOME = os.getenv("INSIGHTFACE_HOME", "/runpod-volume/insightface")
_lock = threading.Lock()
_analyser: Any = None
_swapper: Any = None


def download(url: str, suffix: str) -> Path:
    if not url.startswith("https://"):
        raise ValueError("media URL must use HTTPS")
    response = requests.get(url, timeout=(10, 90), stream=True)
    response.raise_for_status()
    length = int(response.headers.get("content-length", "0") or 0)
    if length > MAX_DOWNLOAD:
        raise ValueError("media file is too large")
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    total = 0
    try:
        for chunk in response.iter_content(1024 * 1024):
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise ValueError("media file is too large")
            handle.write(chunk)
        handle.close()
        return Path(handle.name)
    except Exception:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def models():
    global _analyser, _swapper
    if _analyser is None:
        _analyser = FaceAnalysis(name=os.getenv("FACE_ANALYSIS_MODEL", "buffalo_l"), root=HOME, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        _analyser.prepare(ctx_id=0, det_size=(640, 640))
    if _swapper is None:
        model_path = hf_hub_download(
            repo_id=os.getenv("INSWAPPER_REPO", "ezioruan/inswapper_128.onnx"),
            filename=os.getenv("INSWAPPER_FILE", "inswapper_128.onnx"),
            cache_dir=HOME,
            token=os.getenv("HF_TOKEN") or None,
        )
        _swapper = get_model(model_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    return _analyser, _swapper


def largest_face(analyser: Any, frame: np.ndarray):
    faces = analyser.get(frame)
    if not faces:
        raise ValueError("no face detected")
    return max(faces, key=lambda face: float((face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1])))


def swap_frame(analyser: Any, swapper: Any, source: Any, frame: np.ndarray) -> np.ndarray:
    targets = analyser.get(frame)
    result = frame.copy()
    for target in targets:
        result = swapper.get(result, target, source, paste_back=True)
    return result


def image_swap(source: Any, target_path: Path, output_path: Path) -> None:
    analyser, swapper = models()
    target = cv2.imread(str(target_path))
    if target is None:
        raise ValueError("invalid target image")
    if not analyser.get(target):
        raise ValueError("no target face detected")
    result = swap_frame(analyser, swapper, source, target)
    if not cv2.imwrite(str(output_path), result, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError("could not encode result image")


def video_swap(source: Any, target_path: Path, output_path: Path) -> None:
    analyser, swapper = models()
    capture = cv2.VideoCapture(str(target_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not width or not height or frame_count / fps > MAX_VIDEO_SECONDS:
        capture.release()
        raise ValueError("invalid video or video too long")
    silent = Path(tempfile.mktemp(suffix=".mp4"))
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    try:
        seen_face = False
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            faces = analyser.get(frame)
            if faces:
                seen_face = True
                for target in faces:
                    frame = swapper.get(frame, target, source, paste_back=True)
            writer.write(frame)
        if not seen_face:
            raise ValueError("no target face detected")
    finally:
        capture.release()
        writer.release()
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(silent), "-i", str(target_path), "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-c:a", "aac", "-shortest", str(output_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        silent.unlink(missing_ok=True)


def handler(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("input") or {}
    if payload.get("adult_consent_attested") is not True:
        raise ValueError("explicit adult consent attestation is required")
    source_url, target_url = str(payload.get("source_face_url", "")), str(payload.get("target_url", ""))
    is_video = bool(payload.get("is_video", False))
    if not source_url or not target_url:
        raise ValueError("source_face_url and target_url are required")
    source_path = download(source_url, ".jpg")
    target_path = download(target_url, ".mp4" if is_video else ".jpg")
    output_path = Path(tempfile.mktemp(suffix=".mp4" if is_video else ".jpg"))
    try:
        with _lock:
            analyser, _ = models()
            source_image = cv2.imread(str(source_path))
            if source_image is None:
                raise ValueError("invalid source image")
            source = largest_face(analyser, source_image)
            if is_video:
                video_swap(source, target_path, output_path)
            else:
                image_swap(source, target_path, output_path)
        encoded = base64.b64encode(output_path.read_bytes()).decode("ascii")
        return {"result": encoded, "content_type": "video/mp4" if is_video else "image/jpeg"}
    finally:
        source_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
