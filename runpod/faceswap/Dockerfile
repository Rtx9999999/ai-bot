FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    INSIGHTFACE_HOME=/runpod-volume/insightface

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev build-essential ca-certificates ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY runpod/faceswap/requirements.txt ./requirements.txt
RUN python3 -m pip install --upgrade pip && python3 -m pip install -r requirements.txt

COPY runpod/faceswap/handler.py ./handler.py
# The entrypoint calls runpod.serverless.start({"handler": handler}).
CMD ["python3", "-u", "handler.py"]
