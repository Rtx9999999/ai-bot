MODELS = {
    "pony": "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
    "realistic": "realisticVisionV51_v51VAE.safetensors",
    "juggernaut": "juggernautXL_v9Rdphoto2Lightning.safetensors",
}
STYLES = {
    "realiste": "photorealistic, cinematic lighting, highly detailed",
    "anime": "anime illustration, detailed linework, vibrant colors",
    "hentai": "adult anime illustration, highly detailed",
    "furry": "anthropomorphic adult character, detailed fur, digital art",
    "cartoon": "adult cartoon illustration, polished, expressive",
    "fantasy": "adult dark fantasy art, intricate, cinematic",
}
LEVELS = {
    "soft": "sensual adult, tasteful, suggestive",
    "explicite": "explicit adult content",
    "hardcore": "hardcore consensual adult content",
}
RATIOS = {"1:1": (1024, 1024), "9:16": (576, 1024), "16:9": (1024, 576), "4:5": (816, 1024)}
RESOLUTIONS = {"512": 512, "768": 768, "1024": 1024}
NEGATIVE_PROMPT = (
    "child, children, kid, minor, teen, young-looking, underage, loli, shota, "
    "rape, forced, coercion, unconscious, asleep, drugged, non-consensual, incest, "
    "bestiality, gore, mutilation, watermark, text, low quality, blurry, malformed anatomy, "
    "extra fingers, missing fingers, deformed hands"
)
PACKS = {5: 199, 20: 599, 50: 1199, 100: 1999}  # Stars
PREMIUM_STARS = 2499
PREMIUM_USD = 24.99

