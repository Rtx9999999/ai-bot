import asyncio
import io
import uuid
import boto3
from PIL import Image, ImageDraw, ImageFont
from .config import Settings


class Storage:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.client = None
        if cfg.media_backend_ready:
            self.client = boto3.client("s3", endpoint_url=cfg.s3_endpoint_url, aws_access_key_id=cfg.s3_access_key,
                aws_secret_access_key=cfg.s3_secret_key, region_name=cfg.s3_region)

    async def upload(self, data: bytes, ext: str, content_type: str, prefix: str = "media") -> str:
        if self.client is None:
            raise RuntimeError("Stockage R2/S3 non configuré")
        key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
        await asyncio.to_thread(self.client.put_object, Bucket=self.cfg.s3_bucket, Key=key, Body=data, ContentType=content_type)
        return f"{self.cfg.s3_public_url}/{key}"

    async def watermarked(self, data: bytes) -> bytes:
        def draw() -> bytes:
            im = Image.open(io.BytesIO(data)).convert("RGB"); layer = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
            font = ImageFont.load_default(size=max(16, im.width // 35)); text = self.cfg.watermark_text
            box = d.textbbox((0, 0), text, font=font); x, y = im.width - (box[2]-box[0]) - 18, im.height - (box[3]-box[1]) - 18
            d.rounded_rectangle((x-10, y-8, im.width-8, im.height-8), 8, fill=(0, 0, 0, 150)); d.text((x, y), text, font=font, fill="white")
            out = io.BytesIO(); Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB").save(out, "JPEG", quality=88); return out.getvalue()
        return await asyncio.to_thread(draw)
