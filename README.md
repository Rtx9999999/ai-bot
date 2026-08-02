# Bot Telegram de génération artistique 18+

Bot asynchrone prêt pour Railway : images SDXL via RunPod Serverless, vidéos AnimateDiff, face swap InsightFace/Roop, paiements Telegram Stars/SOL/USDT-TRC20, stockage R2/S3, SQLite WAL, galerie, parrainage et administration.

## Garde-fous

Le service est strictement réservé aux personnes majeures. Les prompts impliquant des mineurs, des personnes d'apparence mineure, l'inceste, la bestialité ou l'absence de consentement sont refusés. Le face swap exige une attestation de consentement. L'opérateur doit aussi respecter le droit local, les règles Telegram, les règles des modèles et mettre en place un canal de signalement/retrait.

## Installation locale

Prérequis : Docker et trois endpoints RunPod compatibles avec le contrat ci-dessous.

```sh
cp .env.example .env
# renseigner toutes les valeurs
docker compose up --build -d
docker compose logs -f bot
```

La base est créée automatiquement dans le volume `bot_data`. En exécution Python directe, utilisez Python 3.12, `pip install -r requirements.txt`, puis `python -m app.main`.

## Contrat RunPod

Les endpoints reçoivent un objet RunPod `{ "input": ... }`.

- Image : `prompt`, `negative_prompt`, `model`, `width`, `height`, `steps`, `cfg_scale`, `seed`.
- Vidéo : mêmes champs, plus `duration_seconds`, `fps`, `engine=animatediff`.
- Face swap : `source_face_url`, `target_url`, `is_video`, `engine=insightface_roop`, `adult_consent_attested`.

Le résultat doit contenir `output.image`, `output.video`, `output.result` ou `output.images[0]`, en URL HTTPS ou base64. Exécutez `RUNPOD_API_KEY=... sh setup_runpod.sh` pour tester l'accès API. Les noms de checkpoints sont dans `app/constants.py` et peuvent être adaptés aux fichiers réellement montés dans le Network Volume RunPod.

## Stockage R2

Créez un bucket, des clés S3 et un domaine public/custom domain. Utilisez l'endpoint S3 R2 dans `S3_ENDPOINT_URL`. Avec AWS S3, renseignez l'endpoint/région correspondants. Configurez une politique de rétention et évitez de rendre publics les uploads sources si votre worker sait lire des URL signées; cette implémentation utilise les URL publiques pour l'interopérabilité des workers.

## Paiements

Telegram Stars utilise `sendInvoice` avec `currency=XTR`; aucun provider token n'est nécessaire. Pour SOL et TRC20, chaque commande reçoit un montant unique à six décimales puis `/verify ID` recherche une transaction confirmée de ce montant. `SOL_USD_PRICE` doit être actualisé par l'opérateur; en production à fort volume, branchez un oracle de prix et un indexeur/webhook. Ne réutilisez jamais une adresse de dépôt sur plusieurs instances sans base partagée.

Packs Stars : 5/20/50/100 crédits. Premium ajoute 100 crédits et 30 jours. Une génération image coûte 1 crédit, vidéo 2, face swap 3. Le parrain reçoit 10 % des crédits achetés, au minimum 1.

## Commandes

- `/start [ID]`, `/verify ID`
- `/admin` : statistiques
- `/admin_credit ID N`
- `/admin_ban ID`, `/admin_unban ID`
- `/admin_premium ID JOURS`

## Déploiement Railway

1. Poussez ce dossier dans un dépôt privé et créez un projet Railway depuis ce dépôt.
2. Ajoutez toutes les variables de `.env.example` dans Railway Variables.
3. Ajoutez un volume persistant monté sur `/app/data` (décrit aussi dans `railway.toml`).
4. Déployez, ou connectez Railway CLI puis lancez `sh deploy.sh`.
5. Consultez les logs et lancez `/start`. Une seule réplique doit utiliser SQLite et le polling Telegram. Pour plusieurs répliques, migrez vers PostgreSQL et un webhook avec file de tâches.

## Exploitation

Sauvegardez quotidiennement `/app/data/bot.db` avec son WAL, surveillez les erreurs RunPod et les soldes crypto, faites tourner les secrets, et limitez l'accès au bucket. La montée en charge GPU est gérée par RunPod; le bot lui-même tient plusieurs travaux concurrents grâce aux tâches asyncio. Pour une charge élevée, remplacez les tâches en mémoire par Redis/Celery et SQLite par PostgreSQL.

## Tests

```sh
pip install pytest
pytest -q
```

