import asyncio
import io
import uuid
import boto3
from botocore.config import Config
from PIL import Image, ImageDraw, ImageFont
from .config import Settings, configured


class Storage:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.client = None
        if cfg.media_backend_ready:
            try:
                self.client = boto3.client("s3", endpoint_url=cfg.s3_endpoint_url, aws_access_key_id=cfg.s3_access_key,
                    aws_secret_access_key=cfg.s3_secret_key, region_name=cfg.s3_region,
                    config=Config(signature_version="s3v4"))
            except ValueError:
                self.client = None

    async def upload(self, data: bytes, ext: str, content_type: str, prefix: str = "media") -> str:
        if self.client is None:
            raise RuntimeError("Stockage R2/S3 non configuré")
        key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
        await asyncio.to_thread(self.client.put_object, Bucket=self.cfg.s3_bucket, Key=key, Body=data, ContentType=content_type)
        if configured(self.cfg.s3_public_url):
            return f"{self.cfg.s3_public_url}/{key}"
        return f"s3://{self.cfg.s3_bucket}/{key}"

    async def url(self, reference: str, expires: int = 3600) -> str:
        """Resolve a private S3 reference to a short-lived HTTPS URL."""
        if not reference.startswith("s3://"):
            return reference
        if self.client is None:
            raise RuntimeError("Stockage R2/S3 non configuré")
        bucket_and_key = reference[5:]
        bucket, separator, key = bucket_and_key.partition("/")
        if not separator or not bucket or not key:
            raise ValueError("Référence R2/S3 invalide")
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=max(60, min(expires, 604800)),
        )

    async def watermarked(self, data: bytes) -> bytes:
        def draw() -> bytes:
            im = Image.open(io.BytesIO(data)).convert("RGB"); layer = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
            font = ImageFont.load_default(size=max(16, im.width // 35)); text = self.cfg.watermark_text
            box = d.textbbox((0, 0), text, font=font); x, y = im.width - (box[2]-box[0]) - 18, im.height - (box[3]-box[1]) - 18
            d.rounded_rectangle((x-10, y-8, im.width-8, im.height-8), 8, fill=(0, 0, 0, 150)); d.text((x, y), text, font=font, fill="white")
            out = io.BytesIO(); Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB").save(out, "JPEG", quality=88); return out.getvalue()
        return await asyncio.to_thread(draw)
