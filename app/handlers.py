import asyncio
import json
import logging
from html import escape
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from aiogram import Bot, F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from . import keyboards as kb
from .config import Settings
from .chat import ChatAssistant
from .constants import LEVELS, MODELS, NEGATIVE_PROMPT, PACKS, PREMIUM_STARS, RATIOS, RESOLUTIONS, STYLES
from .db import Database, now
from .payments import CryptoPayments
from .runpod import RunPod
from .security import RateLimiter, validate_prompt, validate_real_photo_edit
from .storage import Storage

log = logging.getLogger(__name__)


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    async def __call__(self, handler, event, data):
        channel = self.cfg.required_channel_username
        if not channel or event.from_user.id in self.cfg.admins:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "subscription:check":
            return await handler(event, data)
        try:
            member = await event.bot.get_chat_member(self.cfg.required_channel_chat, event.from_user.id)
            subscribed = member.status in {"creator", "administrator", "member", "restricted"}
        except Exception:
            log.exception("channel subscription middleware failed")
            if isinstance(event, Message):
                await event.answer(
                    "📢 Vérification du canal indisponible pour le moment. Réessayez dans quelques instants.",
                    reply_markup=kb.subscription(channel),
                )
            else:
                await event.answer("Vérification du canal indisponible.", show_alert=True)
            return None
        if subscribed:
            return await handler(event, data)
        text = "📢 Pour utiliser ce bot, vous devez d'abord vous abonner à notre canal.\n\nAbonnez-vous, puis appuyez sur « Vérifier mon abonnement »."
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb.subscription(channel))
        else:
            await event.answer("Abonnement requis.", show_alert=True)
            await event.message.answer(text, reply_markup=kb.subscription(channel))
        return None

class Flow(StatesGroup): prompt=State(); face=State(); swap_media=State(); crypto_pack=State(); outfit_photo=State(); clone_token=State()


def create_router(cfg: Settings, db: Database, runpod: RunPod, storage: Storage, payments: CryptoPayments, limiter: RateLimiter, chat: ChatAssistant, start_clone: Callable[[int, str], Awaitable[str]] | None = None, stop_clone: Callable[[int, int], Awaitable[bool]] | None = None):
    r=Router()
    generation_slots = asyncio.Semaphore(cfg.max_concurrent_generations)
    queue_lock = asyncio.Lock()
    queue_waiting = 0
    subscription_middleware = SubscriptionMiddleware(cfg)
    r.message.outer_middleware(subscription_middleware)
    r.callback_query.outer_middleware(subscription_middleware)
    welcome=(
        "👋 Bienvenue ! Je suis votre secrétaire créative IA.\n\n"
        "Je vous accompagne pour créer vos images et vidéos, gérer votre galerie "
        "et suivre vos crédits. Choisissez une option ci-dessous pour commencer :"
    )

    async def is_subscribed(bot: Bot, user_id: int) -> bool:
        channel = cfg.required_channel_username
        if not channel or user_id in cfg.admins:
            return True
        try:
            member = await bot.get_chat_member(cfg.required_channel_chat, user_id)
            return member.status in {"creator", "administrator", "member", "restricted"}
        except Exception:
            log.exception("channel subscription check failed")
            return False

    async def require_subscription(event: Message | CallbackQuery) -> bool:
        if await is_subscribed(event.bot, event.from_user.id):
            return True
        text = "📢 Pour utiliser ce bot, vous devez d'abord vous abonner à notre canal.\n\nAbonnez-vous, puis appuyez sur « Vérifier mon abonnement »."
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb.subscription(cfg.required_channel_username))
        else:
            await event.answer("Abonnement requis.", show_alert=True)
            await event.message.answer(text, reply_markup=kb.subscription(cfg.required_channel_username))
        return False

    async def user_ok(event):
        uid=event.from_user.id; u=await db.one("SELECT * FROM users WHERE id=?",(uid,))
        if u and u["banned"]:
            await (event.answer("Accès suspendu.") if isinstance(event,Message) else event.answer("Accès suspendu.",show_alert=True)); return None
        return u

    @r.message(Command("start"))
    async def start(m:Message, command:CommandObject):
        ref=int(command.args) if command.args and command.args.isdigit() else None
        u=await db.ensure_user(m.from_user.id,m.from_user.username,cfg.free_credits,ref)
        if u["banned"]: return await m.answer("Accès suspendu.")
        if not await require_subscription(m): return
        if not u["age_verified"]: return await m.answer("🔞 Ce bot est strictement réservé aux adultes. Confirmez votre âge. Les contenus impliquant des mineurs ou l'absence de consentement sont interdits.",reply_markup=kb.age())
        await m.answer(welcome,reply_markup=kb.main())

    @r.callback_query(F.data=="subscription:check")
    async def subscription_check(c: CallbackQuery):
        if not await is_subscribed(c.bot, c.from_user.id):
            return await c.answer("Abonnement non détecté. Rejoignez le canal puis réessayez.", show_alert=True)
        await c.answer("Abonnement confirmé !")
        u = await db.ensure_user(c.from_user.id, c.from_user.username, cfg.free_credits)
        if not u["age_verified"]:
            return await c.message.edit_text("🔞 Ce bot est strictement réservé aux adultes. Confirmez votre âge.", reply_markup=kb.age())
        await c.message.edit_text(welcome, reply_markup=kb.main())

    @r.callback_query(F.data=="age:yes")
    async def verify_age(c:CallbackQuery):
        await db.execute("UPDATE users SET age_verified=1,updated_at=? WHERE id=?",(now(),c.from_user.id)); await c.message.edit_text(welcome,reply_markup=kb.main()); await c.answer()
    @r.callback_query(F.data=="age:no")
    async def reject_age(c:CallbackQuery): await c.message.edit_text("Accès refusé : ce service est réservé aux 18+."); await c.answer()
    @r.callback_query(F.data=="home")
    async def home(c:CallbackQuery,state:FSMContext): await state.clear(); await c.message.edit_text(welcome,reply_markup=kb.main()); await c.answer()
    @r.callback_query(F.data=="noop")
    async def noop(c:CallbackQuery): await c.answer()

    @r.callback_query(F.data.in_({"gen","gen_hd","photo_custom","random_gen","theme_gen","video"}))
    async def begin(c:CallbackQuery,state:FSMContext):
        u=await user_ok(c)
        if not u or not u["age_verified"]: return
        kind="video" if c.data=="video" else "gen"
        if not cfg.generation_backend_ready(kind):
            return await c.answer("Génération indisponible : configurez RunPod et R2 dans Railway.",show_alert=True)
        await state.clear(); await state.update_data(kind=kind,quality="hd" if c.data=="gen_hd" else "standard",entry=c.data); await c.message.edit_text("Choisissez le modèle :",reply_markup=kb.models()); await c.answer()

    @r.callback_query(F.data=="outfit_photo")
    async def outfit_start(c:CallbackQuery,state:FSMContext):
        if not cfg.generation_backend_ready("gen"):
            return await c.answer("Modification indisponible : configurez RunPod et R2 dans Railway.",show_alert=True)
        await state.clear(); await state.set_state(Flow.outfit_photo)
        await c.message.edit_text("👗 Envoie la photo à modifier. La personne doit être majeure et consentante. Seuls les changements de tenue non nus sont acceptés.")
        await c.answer()

    @r.message(Flow.outfit_photo,F.photo)
    async def outfit_upload(m:Message,state:FSMContext):
        f=await m.bot.get_file(m.photo[-1].file_id); buf=await m.bot.download_file(f.file_path)
        if len(buf.getvalue())>cfg.max_upload_mb*1024*1024:return await m.answer("Fichier trop volumineux.")
        ref=await storage.upload(buf.getvalue(),"jpg","image/jpeg","uploads")
        url=await storage.url(ref)
        await state.update_data(kind="gen",entry="outfit_photo",target_url=url,model="realistic",style="realiste",level="soft",ratio="1:1",resolution="1024")
        await state.set_state(Flow.prompt)
        await m.answer("Décris la nouvelle tenue souhaitée. La nudité ou la transparence explicite sur une personne réelle sera refusée.")

    @r.callback_query(F.data=="daily_bonus")
    async def daily_bonus(c:CallbackQuery):
        day=datetime.now(timezone.utc).date().isoformat(); external=f"daily:{c.from_user.id}:{day}"
        existing=await db.one("SELECT id FROM transactions WHERE external_id=?",(external,))
        if existing:return await c.answer("Tu as déjà récupéré ton bonus aujourd'hui.",show_alert=True)
        await db.execute("INSERT INTO transactions(user_id,provider,external_id,amount,currency,credits,status,metadata,created_at) VALUES(?,?,?,0,'CREDIT',1,'paid','{}',?)",(c.from_user.id,"daily",external,now()))
        await db.credit(c.from_user.id,1); await c.answer("🎁 +1 crédit ajouté !",show_alert=True)

    @r.callback_query(F.data=="support")
    async def support(c:CallbackQuery):
        await c.message.edit_text("❓ Aide et support\n\n/start — afficher le menu\n/verify ID — vérifier un paiement SOL\n\nPour toute demande, contactez l'administrateur du bot.",reply_markup=kb.rows((("↩️ Menu","home"),))); await c.answer()

    @r.callback_query(F.data.startswith("set:"))
    async def settings(c:CallbackQuery,state:FSMContext):
        _,key,value=c.data.split(":",2); await state.update_data(**{key:value}); data=await state.get_data()
        if key=="model": text,markup="Choisissez le style :",kb.choices("style",list(STYLES))
        elif key=="style": text,markup="Niveau de contenu (18+ et consentant uniquement) :",kb.choices("level",list(LEVELS))
        elif key=="level": text,markup="Choisissez le ratio :",kb.choices("ratio",list(RATIOS))
        elif key=="ratio" and data.get("kind")=="gen": text,markup="Choisissez la résolution :",kb.choices("resolution",list(RESOLUTIONS))
        elif key=="ratio" and data.get("kind")=="video": text,markup="Choisissez la durée :",kb.choices("duration",["2","3","4","5"])
        else:
            await state.set_state(Flow.prompt); text="Envoyez votre prompt personnalisé. Les mots-clés avancés et pondérations `(mot:1.2)` sont acceptés."; markup=None
        await c.message.edit_text(text,reply_markup=markup); await c.answer()

    @r.message(Flow.prompt,F.text)
    async def prompt(m:Message,state:FSMContext):
        d=await state.get_data()
        validator=validate_real_photo_edit if d.get("entry")=="outfit_photo" else validate_prompt
        ok,reason=validator(m.text)
        if not ok:return await m.answer(reason)
        await state.update_data(prompt=m.text); d=await state.get_data()
        await m.answer(f"Confirmer :\n\n{m.text}\n\nModèle: {d['model']} · Style: {d['style']} · Niveau: {d['level']} · Ratio: {d['ratio']}",reply_markup=kb.confirm())

    async def process_generation(m:Message,uid:int,data:dict):
        nonlocal queue_waiting
        kind=data["kind"]; cost=2 if kind=="video" else 1
        if not await db.debit(uid,cost): return await m.edit_text("Crédits insuffisants.",reply_markup=kb.shop())
        gid=await db.new_generation(uid,kind,data["prompt"],data)
        async with queue_lock:
            queue_waiting += 1; position = queue_waiting
        status=await m.edit_text(f"🕐 File d'attente — position {position}")
        async with generation_slots:
            async with queue_lock: queue_waiting = max(0, queue_waiting - 1)
            await status.edit_text("⏳ Génération en cours… 0%")
            task=asyncio.create_task(_animate(status)); job=None
            try:
                rw,rh=RATIOS[data["ratio"]]; size=RESOLUTIONS.get(data.get("resolution","1024"),1024); scale=size/max(rw,rh); w,h=int(rw*scale)//8*8,int(rh*scale)//8*8
                payload={"prompt":f"adult, 18+, consensual, {STYLES[data['style']]}, {LEVELS[data['level']]}, {data['prompt']}","negative_prompt":NEGATIVE_PROMPT,"model":MODELS[data['model']],"width":w,"height":h,"steps":30,"cfg_scale":7,"seed":-1}
                if data.get("target_url"):
                    payload.update({"input_image_url":data["target_url"],"task":"outfit_change","preserve_identity":True,"require_clothed_output":True})
                if kind=="video": payload.update({"duration_seconds":int(data.get("duration",3)),"fps":12,"engine":"animatediff"})
                endpoint=cfg.runpod_video_endpoint if kind=="video" else cfg.runpod_image_endpoint
                job,out=await runpod.submit(endpoint,payload); raw,ctype=await runpod.output_bytes(out); ext="mp4" if kind=="video" else "png"; ref=await storage.upload(raw,ext,ctype,"generations")
                await db.execute("UPDATE generations SET status='completed',runpod_job_id=?,result_url=? WHERE id=?",(job,ref,gid)); task.cancel()
                if kind=="video": await m.bot.send_video(uid,BufferedInputFile(raw,"creation.mp4"),caption="✅ Vidéo terminée")
                else:
                    preview=await storage.watermarked(raw); await m.bot.send_photo(uid,BufferedInputFile(preview,"preview.jpg"),caption="✅ Aperçu filigrané. L'original est conservé dans votre galerie.")
                await status.edit_text("✅ Génération terminée.",reply_markup=kb.main())
            except Exception as e:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                error = str(e).strip() or e.__class__.__name__
                await db.credit(uid,cost)
                await db.execute(
                    "UPDATE generations SET status='failed',runpod_job_id=?,error=? WHERE id=?",
                    (job, error[:1000], gid),
                )
                log.exception("generation failed")
                await status.edit_text(
                    f"Échec de génération: {error[:180]}. Vos crédits ont été remboursés.",
                    reply_markup=kb.main(),
                )

    async def _animate(msg:Message):
        try:
            for pct in (15,30,45,60,75,90,95):
                await asyncio.sleep(4)
                await msg.edit_text(f"⏳ Génération en cours… {pct}%")
        except (asyncio.CancelledError,Exception): pass

    @r.callback_query(F.data=="generate:go")
    async def generate(c:CallbackQuery,state:FSMContext):
        if not limiter.allowed(c.from_user.id): return await c.answer("Patientez quelques secondes.",show_alert=True)
        data=await state.get_data(); await state.clear(); await c.answer(); asyncio.create_task(process_generation(c.message,c.from_user.id,data))

    @r.callback_query(F.data=="profile")
    async def profile(c:CallbackQuery):
        u=await db.one("SELECT * FROM users WHERE id=?",(c.from_user.id,)); premium=u["premium_until"] or "inactif"
        me=await c.bot.get_me(); await c.message.edit_text(f"👤 @{u['username'] or '-'}\nCrédits : {u['credits']}\nPremium jusqu'au : {premium}\nLien de parrainage : https://t.me/{me.username}?start={u['id']}",reply_markup=kb.main()); await c.answer()

    @r.callback_query(F.data=="referral")
    async def referral(c:CallbackQuery):
        me=await c.bot.get_me()
        stats=await db.one("SELECT COUNT(*) invited,COALESCE(SUM(bonus_credits),0) bonus FROM referrals WHERE referrer_id=?",(c.from_user.id,))
        link=f"https://t.me/{me.username}?start={c.from_user.id}"
        await c.message.edit_text(f"🤝 Parrainage\n\nInvités : {stats['invited']}\nCrédits gagnés : {stats['bonus']}\nBonus : {cfg.referral_bonus_percent} % des crédits achetés par vos filleuls.\n\nVotre lien :\n{link}",reply_markup=kb.rows((("↩️ Menu","home"),))); await c.answer()

    @r.callback_query(F.data=="backup_bot")
    async def backup_bot(c:CallbackQuery):
        username=cfg.backup_bot_username.lstrip("@").strip()
        if not username:
            return await c.answer("Le bot de secours sera bientôt disponible.",show_alert=True)
        await c.message.edit_text(f"🛡️ Bot de secours\n\nEnregistrez ce second bot pour conserver un accès au service :\nhttps://t.me/{username}",reply_markup=kb.rows((("↩️ Menu","home"),))); await c.answer()

    @r.callback_query(F.data=="clone_bot")
    async def clone_bot(c: CallbackQuery, state: FSMContext):
        if start_clone is None or not cfg.clone_encryption_key:
            return await c.answer("Le clonage est temporairement indisponible.", show_alert=True)
        await state.clear()
        await state.set_state(Flow.clone_token)
        clones = await db.all("SELECT bot_id,username,active FROM clone_bots WHERE owner_id=? ORDER BY id DESC", (c.from_user.id,))
        buttons = [[kb.B(text=f"🛑 Désactiver @{x['username']}", callback_data=f"clone:disable:{x['bot_id']}")] for x in clones if x["active"]]
        buttons.append([kb.B(text="➕ Connecter un nouveau clone", callback_data="clone:new")])
        buttons.append([kb.B(text="↩️ Menu", callback_data="home")])
        await c.message.edit_text("🤖 <b>Mes clones</b>\n\nVous pouvez connecter jusqu'à 3 clones.", reply_markup=kb.M(inline_keyboard=buttons))
        await c.answer()

    @r.callback_query(F.data=="clone:new")
    async def clone_new(c: CallbackQuery, state: FSMContext):
        count = await db.one("SELECT COUNT(*) total FROM clone_bots WHERE owner_id=? AND active=1", (c.from_user.id,))
        if count["total"] >= cfg.max_clones_per_user:
            return await c.answer("Limite de clones atteinte.", show_alert=True)
        await state.clear(); await state.set_state(Flow.clone_token)
        await c.message.edit_text(
            "🤖 <b>Cloner ce bot</b>\n\n"
            "1. Ouvrez @BotFather et envoyez /newbot.\n"
            "2. Choisissez le nom et le nom d'utilisateur du clone.\n"
            "3. Utilisez /setuserpic dans @BotFather et mettez la même photo que ce bot.\n"
            "4. Collez ici le token fourni par @BotFather.\n\n"
            "⚠️ Ne partagez jamais ce token ailleurs."
        )
        await c.answer()

    @r.callback_query(F.data.startswith("clone:disable:"))
    async def clone_disable(c: CallbackQuery):
        bot_id = int(c.data.rsplit(":", 1)[1])
        ok = bool(stop_clone and await stop_clone(c.from_user.id, bot_id))
        await c.answer("Clone désactivé." if ok else "Clone introuvable.", show_alert=True)
        await c.message.edit_text("🤖 Clone désactivé. Son token chiffré a été retiré.", reply_markup=kb.main())

    @r.message(Flow.clone_token, F.text)
    async def clone_token(m: Message, state: FSMContext):
        token = m.text.strip()
        try: await m.delete()
        except Exception: pass
        if len(token) < 30 or ":" not in token:
            return await m.answer("Token invalide. Copiez le token complet fourni par @BotFather.")
        await state.clear()
        status = await m.answer("⏳ Vérification et démarrage du clone…")
        try:
            result = await start_clone(m.from_user.id, token)
            await status.edit_text(f"✅ {escape(result)}\n\nLe clone utilise maintenant les mêmes fonctions et le canal obligatoire.", reply_markup=kb.main())
        except ValueError as exc:
            await status.edit_text(f"❌ {escape(str(exc))}", reply_markup=kb.main())
        except Exception:
            log.exception("clone creation failed")
            await status.edit_text("❌ Impossible de démarrer ce clone. Vérifiez le token et réessayez.", reply_markup=kb.main())

    @r.callback_query(F.data.startswith("gallery:"))
    async def gallery(c:CallbackQuery):
        items=await db.all("SELECT * FROM generations WHERE user_id=? AND status='completed' ORDER BY id DESC LIMIT 50",(c.from_user.id,)); i=int(c.data.split(":")[1])
        if not items:return await c.answer("Galerie vide.",show_alert=True)
        i=max(0,min(i,len(items)-1)); x=items[i]; media_url=await storage.url(x["result_url"]); text=f"{x['kind'].upper()} · {x['created_at'][:16]}\n{x['prompt'] or 'Face swap'}\n{media_url}"
        await c.message.edit_text(text,reply_markup=kb.gallery(i,len(items)),disable_web_page_preview=False); await c.answer()

    @r.callback_query(F.data=="shop")
    async def shop(c:CallbackQuery): await c.message.edit_text("Achetez des crédits ou Premium :",reply_markup=kb.shop()); await c.answer()
    @r.callback_query(F.data.startswith("stars:"))
    async def stars(c:CallbackQuery):
        item=c.data.split(":")[1]; premium=item=="premium"; credits=cfg.premium_credits if premium else int(item); amount=PREMIUM_STARS if premium else PACKS[credits]
        payload=f"premium:{c.from_user.id}" if premium else f"credits:{credits}:{c.from_user.id}"
        await c.bot.send_invoice(c.from_user.id,"Premium mensuel" if premium else f"Pack {credits} crédits","Accès au service 18+",payload,"XTR",[LabeledPrice(label="Total",amount=amount)]) ; await c.answer()
    @r.pre_checkout_query()
    async def checkout(q:PreCheckoutQuery):
        try: uid=int(q.invoice_payload.split(":")[-1]); valid=uid==q.from_user.id
        except ValueError: valid=False
        await q.answer(ok=valid,error_message=None if valid else "Facture invalide")
    @r.message(F.content_type==ContentType.SUCCESSFUL_PAYMENT)
    async def paid(m:Message):
        p=m.successful_payment; parts=p.invoice_payload.split(":"); premium=parts[0]=="premium"; credits=cfg.premium_credits if premium else int(parts[1])
        tx=await db.execute("INSERT INTO transactions(user_id,provider,external_id,amount,currency,credits,status,metadata,created_at) VALUES(?,?,?,?,?,?,'pending',?,?)",(m.from_user.id,"stars",p.telegram_payment_charge_id,p.total_amount,"XTR",credits,json.dumps({"premium":premium}),now()))
        await db.complete_payment(tx,p.telegram_payment_charge_id,cfg.premium_days,cfg.referral_bonus_percent); await m.answer("✅ Paiement confirmé. Votre compte a été crédité.",reply_markup=kb.main())

    @r.callback_query(F.data.startswith("crypto:"))
    async def crypto(c:CallbackQuery,state:FSMContext):
        if c.data not in {"crypto:sol", "crypto:eth"}:
            return await c.answer("Ce moyen de paiement n'est pas disponible.", show_alert=True)
        provider=c.data.split(":",1)[1]
        await state.set_state(Flow.crypto_pack); await state.update_data(provider=provider); await c.message.edit_text("Indiquez le nombre de crédits souhaité : 5, 20, 50 ou 100. Envoyez `premium` pour l'abonnement."); await c.answer()
    @r.message(Flow.crypto_pack,F.text)
    async def crypto_pack(m:Message,state:FSMContext):
        val=m.text.lower().strip(); premium=val=="premium"
        if not premium and (not val.isdigit() or int(val) not in PACKS): return await m.answer("Choix invalide : 5, 20, 50, 100 ou premium.")
        credits=cfg.premium_credits if premium else int(val); usd=24.99 if premium else {5:1.99,20:5.99,50:11.99,100:19.99}[credits]; d=await state.get_data(); provider=d["provider"]
        wallet=cfg.solana_wallet if provider=="sol" else cfg.eth_wallet
        if not wallet:return await m.answer("Ce portefeuille de paiement n'est pas encore configuré.")
        txid,amount=await payments.create(m.from_user.id,provider,usd,credits,premium)
        asset="SOL" if provider=="sol" else "ETH"; comment=""
        await state.clear(); await m.answer(f"Envoyez exactement `{amount}` {asset} à :\n`{wallet}`{comment}\n\nPuis utilisez /verify {txid}",parse_mode="Markdown")
    @r.message(Command("verify"))
    async def verify(m:Message,command:CommandObject):
        if not command.args or not command.args.isdigit():return await m.answer("Usage : /verify ID")
        tx=await db.one("SELECT * FROM transactions WHERE id=? AND user_id=?",(int(command.args),m.from_user.id))
        if not tx or tx["status"]!="pending":return await m.answer("Paiement introuvable ou déjà traité.")
        external=await payments.verify(tx)
        if not external:return await m.answer("Paiement confirmé introuvable. Attendez les confirmations puis réessayez.")
        ok=await db.complete_payment(tx["id"],external,cfg.premium_days,cfg.referral_bonus_percent); await m.answer("✅ Paiement confirmé et compte crédité." if ok else "Paiement déjà traité.",reply_markup=kb.main())

    @r.message(Command("reset"))
    async def reset_chat(m: Message):
        await chat.reset(m.from_user.id)
        await m.answer("🧠 Mémoire de la conversation effacée.", reply_markup=kb.main())

    @r.callback_query(F.data=="swap")
    async def swap(c:CallbackQuery,state:FSMContext):
        if not cfg.faceswap_backend_ready:
            return await c.answer("Face swap indisponible : configurez RunPod et R2 dans Railway.",show_alert=True)
        await state.clear(); await state.set_state(Flow.face); await c.message.edit_text("Envoyez une photo nette du visage. Vous devez disposer du consentement explicite de la personne représentée."); await c.answer()
    @r.message(Flow.face,F.photo)
    async def face(m:Message,state:FSMContext):
        f=await m.bot.get_file(m.photo[-1].file_id); buf=await m.bot.download_file(f.file_path)
        if len(buf.getvalue())>cfg.max_upload_mb*1024*1024:return await m.answer("Fichier trop volumineux.")
        ref=await storage.upload(buf.getvalue(),"jpg","image/jpeg","uploads"); url=await storage.url(ref); await state.update_data(face_url=url); await state.set_state(Flow.swap_media); await m.answer("Envoyez maintenant l'image ou la vidéo cible. En l'envoyant, vous attestez avoir le consentement des personnes identifiables.")
    @r.message(Flow.swap_media,F.photo|F.video)
    async def swap_media(m:Message,state:FSMContext):
        if not limiter.allowed(m.from_user.id):return await m.answer("Patientez quelques secondes.")
        media=m.video or m.photo[-1]; f=await m.bot.get_file(media.file_id); buf=await m.bot.download_file(f.file_path)
        if len(buf.getvalue()) > cfg.max_upload_mb * 1024 * 1024:
            return await m.answer("Fichier trop volumineux.")
        cost=3
        if not await db.debit(m.from_user.id,cost):return await m.answer("Crédits insuffisants.",reply_markup=kb.shop())
        is_video=bool(m.video); ext="mp4" if is_video else "jpg"
        target_ref=await storage.upload(buf.getvalue(),ext,"video/mp4" if is_video else "image/jpeg","uploads"); target=await storage.url(target_ref); d=await state.get_data(); await state.clear(); gid=await db.new_generation(m.from_user.id,"faceswap_video" if is_video else "faceswap","",{"consent_attested":True}); status=await m.answer("⏳ Face swap en cours…")
        try:
            job,out=await runpod.submit(cfg.runpod_faceswap_endpoint,{"source_face_url":d["face_url"],"target_url":target,"is_video":is_video,"engine":"insightface_roop","adult_consent_attested":True}); raw,ctype=await runpod.output_bytes(out); result_ref=await storage.upload(raw,ext,ctype,"generations")
            await db.execute("UPDATE generations SET status='completed',runpod_job_id=?,source_url=?,result_url=? WHERE id=?",(job,target_ref,result_ref,gid)); await (m.answer_video(BufferedInputFile(raw,"result.mp4")) if is_video else m.answer_photo(BufferedInputFile(await storage.watermarked(raw),"preview.jpg"))); await status.edit_text("✅ Face swap terminé.",reply_markup=kb.main())
        except Exception as e: await db.credit(m.from_user.id,cost); await db.execute("UPDATE generations SET status='failed',error=? WHERE id=?",(str(e)[:1000],gid)); await status.edit_text("Échec. Crédits remboursés.")

    @r.message(Command("admin"))
    async def admin(m:Message):
        if m.from_user.id not in cfg.admins:return
        s=await db.one("SELECT COUNT(*) users,SUM(credits) credits,SUM(age_verified) verified FROM users"); g=await db.one("SELECT COUNT(*) total,SUM(status='completed') completed FROM generations"); revenue=await db.all("SELECT currency,SUM(amount) amount FROM transactions WHERE status='paid' GROUP BY currency")
        await m.answer(f"Utilisateurs : {s['users']} · vérifiés : {s['verified']} · crédits : {s['credits']}\nGénérations : {g['total']} · terminées : {g['completed']}\nRevenus : {revenue}\n\n/admin_credit ID N\n/admin_ban ID\n/admin_unban ID\n/admin_premium ID JOURS", reply_markup=kb.admin_panel())

    @r.callback_query(F.data.startswith("admin:"))
    async def admin_panel(c: CallbackQuery):
        if c.from_user.id not in cfg.admins: return await c.answer("Accès refusé.", show_alert=True)
        section = c.data.split(":", 1)[1]
        if section == "stats":
            u=await db.one("SELECT COUNT(*) total,SUM(age_verified) verified,SUM(credits) credits FROM users"); g=await db.one("SELECT COUNT(*) total,SUM(status='completed') completed,SUM(status='failed') failed FROM generations")
            text=f"📊 Utilisateurs : {u['total']}\nVérifiés : {u['verified'] or 0}\nCrédits : {u['credits'] or 0}\nGénérations : {g['total']}\nTerminées : {g['completed'] or 0}\nÉchouées : {g['failed'] or 0}"
        elif section == "failures":
            rows=await db.all("SELECT id,kind,error FROM generations WHERE status='failed' ORDER BY id DESC LIMIT 8"); text="⚠️ Derniers échecs\n\n"+"\n".join(f"#{x['id']} {x['kind']} — {(x['error'] or '')[:90]}" for x in rows)
        elif section == "users":
            rows=await db.all("SELECT id,username,credits FROM users ORDER BY created_at DESC LIMIT 10"); text="👥 Nouveaux utilisateurs\n\n"+"\n".join(f"{x['id']} @{x['username'] or '-'} — {x['credits']} crédits" for x in rows)
        else:
            rows=await db.all("SELECT id,provider,currency,amount,status FROM transactions ORDER BY id DESC LIMIT 10"); text="💳 Paiements récents\n\n"+"\n".join(f"#{x['id']} {x['amount']} {x['currency']} — {x['status']}" for x in rows)
        await c.message.edit_text(text or "Aucune donnée.", reply_markup=kb.admin_panel()); await c.answer()
    @r.message(Command("admin_credit","admin_ban","admin_unban","admin_premium"))
    async def admin_action(m:Message,command:CommandObject):
        if m.from_user.id not in cfg.admins:return
        args=(command.args or "").split(); name=m.text.split()[0].split("@")[0]
        try:
            uid=int(args[0])
            if name=="/admin_credit": await db.credit(uid,int(args[1]))
            elif name in {"/admin_ban","/admin_unban"}: await db.execute("UPDATE users SET banned=? WHERE id=?",(1 if name=="/admin_ban" else 0,uid))
            else:
                days=int(args[1]); until=datetime.now(timezone.utc).timestamp()+days*86400; await db.execute("UPDATE users SET premium_until=? WHERE id=?",(datetime.fromtimestamp(until,timezone.utc).isoformat(),uid))
            await m.answer("✅ Action appliquée.")
        except (ValueError,IndexError): await m.answer("Arguments invalides.")

    @r.message(F.text)
    async def chat_message(m: Message):
        u = await db.ensure_user(m.from_user.id, m.from_user.username, cfg.free_credits)
        if u["banned"]:
            return await m.answer("Accès suspendu.")
        if not await require_subscription(m):
            return
        if not u["age_verified"]:
            return await m.answer("Confirmez d'abord votre âge avec /start.")
        if not chat.ready:
            return await m.answer("Le chat IA est en cours d'activation. Utilisez les boutons pour créer une image ou une vidéo.")
        if len(m.text) > 4000:
            return await m.answer("Votre message est trop long. Limitez-le à 4 000 caractères.")
        try:
            await m.bot.send_chat_action(m.chat.id, "typing")
            answer = await chat.reply(m.from_user.id, m.text)
            await m.answer(escape(answer))
        except Exception:
            log.exception("chat response failed")
            await m.answer("Désolée, je n'arrive pas à répondre pour le moment. Réessayez dans quelques instants.")
    return r
