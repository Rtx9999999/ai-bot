FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/runpod-volume/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
COPY runpod/video/requirements.txt ./requirements.txt
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r requirements.txt

COPY runpod/video/handler.py ./handler.py
# The entrypoint calls runpod.serverless.start({"handler": handler}).
CMD ["python3", "-u", "handler.py"]
