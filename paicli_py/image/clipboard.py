"""剪贴板图片抓取。

对应 ``com.paicli.image.ClipboardImage``。
"""

from __future__ import annotations


class ClipboardImage:
    """从系统剪贴板抓取图片。

    支持 Windows / macOS / Linux。
    """

    @staticmethod
    async def grab() -> bytes | None:
        """从剪贴板获取图片数据。

        Returns:
            PNG 格式的图片字节数据，如果剪贴板无图片则返回 None。
        """
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is None:
                return None

            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            return None
