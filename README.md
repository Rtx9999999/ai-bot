# Bot Telegram de gÃ©nÃ©ration artistique 18+

SecrÃ©taire crÃ©ative asynchrone prÃªte pour Railway : images SDXL via RunPod Serverless, vidÃ©os AnimateDiff, face swap InsightFace/Roop, paiements Telegram Stars et SOL, stockage R2/S3, SQLite WAL, galerie, parrainage et administration.

## Garde-fous

Le service est strictement rÃ©servÃ© aux personnes majeures. Les prompts impliquant des mineurs, des personnes d'apparence mineure, l'inceste, la bestialitÃ© ou l'absence de consentement sont refusÃ©s. Le face swap exige une attestation de consentement. L'opÃ©rateur doit aussi respecter le droit local, les rÃ¨gles Telegram, les rÃ¨gles des modÃ¨les et mettre en place un canal de signalement/retrait.

## Installation locale

PrÃ©requis : Docker et trois endpoints RunPod compatibles avec le contrat ci-dessous.

```sh
cp .env.example .env
# renseigner toutes les valeurs
docker compose up --build -d
docker compose logs -f bot
```

La base est crÃ©Ã©e automatiquement dans le volume `bot_data`. En exÃ©cution Python directe, utilisez Python 3.12, `pip install -r requirements.txt`, puis `python -m app.main`.

`TELEGRAM_TOKEN` est la seule variable obligatoire pour dÃ©marrer le bot et afficher les menus. Les alias `BOT_TOKEN` et `TELEGRAM_BOT_TOKEN` sont aussi acceptÃ©s. Sans RunPod et R2/S3, le bot reste en ligne mais les fonctions de gÃ©nÃ©ration et de face swap indiquent qu'elles ne sont pas encore configurÃ©es.

## Contrat RunPod

### Endpoint image fourni

Le worker image se trouve dans `runpod/image`. CrÃ©ez un endpoint Serverless Ã 
partir de ce dÃ©pÃ´t, choisissez le mode **Queue** et indiquez le chemin Dockerfile
`/runpod/image/Dockerfile`. Pour commencer Ã  moindre coÃ»t, utilisez 0 worker
minimum et 1 worker maximum. Attachez un Network Volume afin de conserver le
cache des modÃ¨les dans `/runpod-volume/huggingface` entre les dÃ©marrages.

Le premier appel tÃ©lÃ©charge le modÃ¨le. Ajoutez `HF_TOKEN` aux variables de
l'endpoint si Hugging Face le demande. Les modÃ¨les peuvent Ãªtre remplacÃ©s avec
`MODEL_PONY`, `MODEL_REALISTIC` et `MODEL_JUGGERNAUT`. VÃ©rifiez leurs licences
avant toute exploitation commerciale.

Une fois l'endpoint crÃ©Ã©, copiez son ID dans Railway sous
`RUNPOD_IMAGE_ENDPOINT`.

### Endpoints vidÃ©o et face swap fournis

Deux workers Queue supplÃ©mentaires sont disponibles :

- vidÃ©o AnimateDiff : `/runpod/video/Dockerfile`, Ã  relier Ã 
  `RUNPOD_VIDEO_ENDPOINT` ; utilisez au moins 24 Go de VRAM ;
- face swap InsightFace : `/runpod/faceswap/Dockerfile`, Ã  relier Ã 
  `RUNPOD_FACESWAP_ENDPOINT` ; 16 Go de VRAM suffisent gÃ©nÃ©ralement.

Le worker vidÃ©o produit des clips MP4 de 2 Ã  5 secondes. Realistic Vision 5.1
Ã©tant un modÃ¨le SD1.5 incompatible avec l'adaptateur AnimateDiff SDXL choisi,
son option vidÃ©o utilise par dÃ©faut `SG161222/RealVisXL_V4.0`. Elle peut Ãªtre
remplacÃ©e avec `MODEL_VIDEO_REALISTIC`.

Le worker face swap accepte les images et les vidÃ©os courtes, exige le champ
`adult_consent_attested=true` et conserve l'audio lorsqu'il existe. Il ne doit
Ãªtre utilisÃ© que sur des personnes majeures ayant explicitement consenti. Les
fichiers sont traitÃ©s dans des fichiers temporaires supprimÃ©s aprÃ¨s chaque job.

Pour limiter les coÃ»ts, configurez chaque endpoint avec 0 worker actif et 1
worker maximum. Un Network Volume amÃ©liore les redÃ©marrages, mais engendre un
coÃ»t de stockage persistant ; commencez sans volume si le budget est prioritaire.
VÃ©rifiez les licences de chaque modÃ¨le, notamment avant toute exploitation
commerciale.

Les endpoints reÃ§oivent un objet RunPod `{ "input": ... }`.

- Image : `prompt`, `negative_prompt`, `model`, `width`, `height`, `steps`, `cfg_scale`, `seed`.
- VidÃ©o : mÃªmes champs, plus `duration_seconds`, `fps`, `engine=animatediff`.
- Face swap : `source_face_url`, `target_url`, `is_video`, `engine=insightface_roop`, `adult_consent_attested`.

Le rÃ©sultat doit contenir `output.image`, `output.video`, `output.result` ou `output.images[0]`, en URL HTTPS ou base64. ExÃ©cutez `RUNPOD_API_KEY=... sh setup_runpod.sh` pour tester l'accÃ¨s API. Les noms de checkpoints sont dans `app/constants.py` et peuvent Ãªtre adaptÃ©s aux fichiers rÃ©ellement montÃ©s dans le Network Volume RunPod.

## Stockage R2

CrÃ©ez un bucket, des clÃ©s S3 et un domaine public/custom domain. Utilisez l'endpoint S3 R2 dans `S3_ENDPOINT_URL`. Avec AWS S3, renseignez l'endpoint/rÃ©gion correspondants. Configurez une politique de rÃ©tention et Ã©vitez de rendre publics les uploads sources si votre worker sait lire des URL signÃ©es; cette implÃ©mentation utilise les URL publiques pour l'interopÃ©rabilitÃ© des workers.

## Paiements

Telegram Stars utilise `sendInvoice` avec `currency=XTR` ; aucun jeton de fournisseur n'est nÃ©cessaire. Pour SOL, chaque commande reÃ§oit un montant unique Ã  six dÃ©cimales, puis `/verify ID` recherche une transaction confirmÃ©e de ce montant. `SOL_USD_PRICE` doit Ãªtre actualisÃ© par l'opÃ©rateur ; en production Ã  fort volume, branchez un oracle de prix et un indexeur ou webhook. Ne rÃ©utilisez jamais une adresse de dÃ©pÃ´t sur plusieurs instances sans base partagÃ©e.

Packs Stars : 5/20/50/100 crÃ©dits. Premium ajoute 100 crÃ©dits et 30 jours. Une gÃ©nÃ©ration image coÃ»te 1 crÃ©dit, vidÃ©o 2, face swap 3. Le parrain reÃ§oit 10 % des crÃ©dits achetÃ©s, au minimum 1.

## Commandes

- `/start [ID]`, `/verify ID`
- `/admin` : statistiques
- `/admin_credit ID N`
- `/admin_ban ID`, `/admin_unban ID`
- `/admin_premium ID JOURS`

## DÃ©ploiement Railway

1. Poussez ce dossier dans un dÃ©pÃ´t privÃ© et crÃ©ez un projet Railway depuis ce dÃ©pÃ´t.
2. Ajoutez toutes les variables de `.env.example` dans Railway Variables.
3. Ajoutez un volume persistant montÃ© sur `/app/data` (dÃ©crit aussi dans `railway.toml`).
4. DÃ©ployez, ou connectez Railway CLI puis lancez `sh deploy.sh`.
5. Consultez les logs et lancez `/start`. Une seule rÃ©plique doit utiliser SQLite et le polling Telegram. Pour plusieurs rÃ©pliques, migrez vers PostgreSQL et un webhook avec file de tÃ¢ches.

## Exploitation

Sauvegardez quotidiennement `/app/data/bot.db` avec son WAL, surveillez les erreurs RunPod et les soldes crypto, faites tourner les secrets, et limitez l'accÃ¨s au bucket. La montÃ©e en charge GPU est gÃ©rÃ©e par RunPod; le bot lui-mÃªme tient plusieurs travaux concurrents grÃ¢ce aux tÃ¢ches asyncio. Pour une charge Ã©levÃ©e, remplacez les tÃ¢ches en mÃ©moire par Redis/Celery et SQLite par PostgreSQL.

## Tests

```sh
pip install pytest
pytest -q
```
