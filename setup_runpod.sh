#!/usr/bin/env sh
set -eu
: "${RUNPOD_API_KEY:?RUNPOD_API_KEY requis}"
cat <<'EOF'
Configuration RunPod requise (trois endpoints Serverless):
1. Image SDXL: worker compatible Stable Diffusion WebUI/ComfyUI, modèles Pony V6 XL,
   Realistic Vision 5.1 et Juggernaut XL montés dans /models.
2. Vidéo: worker AnimateDiff SDXL acceptant prompt, negative_prompt, width, height,
   duration_seconds, fps et engine.
3. Face swap: worker InsightFace/Roop acceptant source_face_url, target_url et is_video.

Chaque worker doit répondre dans output avec image, video, result ou images[0], sous
forme d'URL HTTPS ou de base64. Copiez ensuite les trois IDs dans .env.
EOF
curl -fsS -H "Authorization: Bearer ${RUNPOD_API_KEY}" https://api.runpod.ai/graphql -o /dev/null
echo "Clé RunPod valide et API joignable."

