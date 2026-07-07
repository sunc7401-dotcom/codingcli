"""图片处理器 —— 缩放、压缩。

对应 ``com.paicli.image.ImageProcessor``。
"""

from __future__ import annotations

from io import BytesIO


class ImageProcessor:
    """处理图片以适应 LLM 输入要求。"""

    MAX_DIMENSION = 2048
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    JPEG_QUALITY = 85

    @classmethod
    def process(cls, image_data: bytes) -> bytes:
        """缩放并压缩图片。"""
        try:
            from PIL import Image

            img = Image.open(BytesIO(image_data))

            # 缩放大图
            if img.width > cls.MAX_DIMENSION or img.height > cls.MAX_DIMENSION:
                ratio = min(cls.MAX_DIMENSION / img.width, cls.MAX_DIMENSION / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            # 转为 RGB（处理 RGBA/PNG）
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            buf = BytesIO()
            img.save(buf, format="JPEG", quality=cls.JPEG_QUALITY)
            return buf.getvalue()

        except ImportError:
            return image_data

    @classmethod
    def to_base64(cls, image_data: bytes) -> str:
        """将图片转为 base64 字符串。"""
        import base64
        return base64.b64encode(image_data).decode("ascii")
