#!/usr/bin/env sh
set -eu
command -v railway >/dev/null 2>&1 || { echo "Installez Railway CLI: npm i -g @railway/cli"; exit 1; }
test -f .env || { echo "Créez .env depuis .env.example"; exit 1; }
railway up --detach
echo "Déploiement envoyé. Vérifiez avec: railway logs"

