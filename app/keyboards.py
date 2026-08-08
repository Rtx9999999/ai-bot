from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def rows(*items): return M(inline_keyboard=[[B(text=t, callback_data=d) for t,d in row] for row in items])
def main():
    return M(inline_keyboard=[
        [B(text="ðŸ”¥ Image artistique HOT", callback_data="gen"), B(text="â­ Image HD", callback_data="gen_hd")],
        [B(text="âœï¸ Photo personnalisÃ©e", callback_data="photo_custom"), B(text="ðŸŽ¬ VidÃ©o personnalisÃ©e", callback_data="video")],
        [B(text="ðŸŽ² IA alÃ©atoire", callback_data="random_gen"), B(text="ðŸŽ­ SÃ©ance Ã  thÃ¨me", callback_data="theme_gen")],
        [B(text="ðŸ‘— Changer tenue (photo)", callback_data="outfit_photo"), B(text="ðŸ”„ Face swap consenti", callback_data="swap")],
        [B(text="ðŸŽ Bonus quotidien", callback_data="daily_bonus"), B(text="ðŸ’³ Recharger", callback_data="shop")],
        [B(text="ðŸ‘¤ Mon profil", callback_data="profile"), B(text="ðŸ–¼ Ma galerie", callback_data="gallery:0")],
        [B(text="ðŸ“š CommunautÃ©", url="https://t.me/telegram"), B(text="â“ Aide et support", callback_data="support")],
    ])
def age(): return rows((("âœ… Je certifie avoir 18 ans ou plus", "age:yes"),), (("âŒ Quitter", "age:no"),))
def models(): return rows((("Pony V6 XL","set:model:pony"),),( ("Realistic Vision 5.1","set:model:realistic"),),( ("Juggernaut XL","set:model:juggernaut"),))
def choices(kind, values):
    return M(inline_keyboard=[[B(text=x.title(), callback_data=f"set:{kind}:{x}") for x in values[i:i+2]] for i in range(0,len(values),2)])
def confirm(): return rows((("ðŸš€ Lancer (1 crÃ©dit)","generate:go"),),( ("âŒ Annuler","home"),))
def shop(): return rows((("5 crÃ©dits â€” 199 â­","stars:5"),),( ("20 crÃ©dits â€” 599 â­","stars:20"),),( ("50 crÃ©dits â€” 1199 â­","stars:50"),),( ("100 crÃ©dits â€” 1999 â­","stars:100"),),( ("ðŸ‘‘ Premium â€” 2499 â­","stars:premium"),),( ("â—Ž Payer en SOL","crypto:sol"),),(("â†©ï¸ Menu","home"),))
def gallery(index, total):
    nav=[]
    if index>0: nav.append(B(text="â¬…ï¸",callback_data=f"gallery:{index-1}"))
    nav.append(B(text=f"{index+1}/{total}",callback_data="noop"))
    if index+1<total: nav.append(B(text="âž¡ï¸",callback_data=f"gallery:{index+1}"))
    return M(inline_keyboard=[nav,[B(text="â†©ï¸ Menu",callback_data="home")]])
