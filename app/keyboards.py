from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def rows(*items): return M(inline_keyboard=[[B(text=t, callback_data=d) for t,d in row] for row in items])
def main():
    return M(inline_keyboard=[
        [B(text="🔥 Image", callback_data="gen"), B(text="⭐ Image HD", callback_data="gen_hd")],
        [B(text="✍️ Photo", callback_data="photo_custom"), B(text="🎬 Vidéo", callback_data="video")],
        [B(text="🎲 Aléatoire", callback_data="random_gen"), B(text="🎭 Thème", callback_data="theme_gen")],
        [B(text="👗 Changer la tenue", callback_data="outfit_photo")],
        [B(text="🔄 Face swap consenti", callback_data="swap")],
        [B(text="🎁 Bonus quotidien", callback_data="daily_bonus"), B(text="💳 Recharger", callback_data="shop")],
        [B(text="👤 Profil", callback_data="profile"), B(text="🖼 Galerie", callback_data="gallery:0")],
        [B(text="🤝 Parrainage", callback_data="referral"), B(text="🛡️ Bot de secours", callback_data="backup_bot")],
        [B(text="🤖 Cloner le bot", callback_data="clone_bot")],
        [B(text="📚 Communauté", url="https://t.me/telegram"), B(text="❓ Aide et support", callback_data="support")],
    ])
def age(): return rows((("✅ Je certifie avoir 18 ans ou plus", "age:yes"),), (("❌ Quitter", "age:no"),))

def subscription(channel: str):
    username = channel.lstrip("@")
    return M(inline_keyboard=[
        [B(text="📢 Rejoindre le canal", url=f"https://t.me/{username}")],
        [B(text="✅ Vérifier mon abonnement", callback_data="subscription:check")],
    ])
def models(): return rows((("Pony V6 XL","set:model:pony"),),( ("Realistic Vision 5.1","set:model:realistic"),),( ("Juggernaut XL","set:model:juggernaut"),))
def choices(kind, values):
    return M(inline_keyboard=[[B(text=x.title(), callback_data=f"set:{kind}:{x}") for x in values[i:i+2]] for i in range(0,len(values),2)])
def confirm(): return rows((("🚀 Lancer (1 crédit)","generate:go"),),( ("❌ Annuler","home"),))
def shop(): return rows((("5 crédits — 199 ⭐","stars:5"),),( ("20 crédits — 599 ⭐","stars:20"),),( ("50 crédits — 1199 ⭐","stars:50"),),( ("100 crédits — 1999 ⭐","stars:100"),),( ("👑 Premium — 2499 ⭐","stars:premium"),),( ("◎ Payer en SOL","crypto:sol"),),( ("💎 Payer en TON (GRAM)","crypto:ton"),),(("↩️ Menu","home"),))
def gallery(index, total):
    nav=[]
    if index>0: nav.append(B(text="⬅️",callback_data=f"gallery:{index-1}"))
    nav.append(B(text=f"{index+1}/{total}",callback_data="noop"))
    if index+1<total: nav.append(B(text="➡️",callback_data=f"gallery:{index+1}"))
    return M(inline_keyboard=[nav,[B(text="↩️ Menu",callback_data="home")]])

def admin_panel(): return rows(
    (("📊 Statistiques", "admin:stats"), ("⚠️ Échecs", "admin:failures")),
    (("👥 Utilisateurs", "admin:users"), ("💳 Paiements", "admin:payments")),
    (("↩️ Menu", "home"),),
)
