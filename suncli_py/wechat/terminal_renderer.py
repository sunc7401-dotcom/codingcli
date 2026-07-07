"""微信终端渲染器 —— 对应 ``com.paicli.wechat.WechatTerminalRenderer``。"""

import sys

import qrcode  # type: ignore


class WechatTerminalRenderer:
    """在终端中渲染微信 QR 码。"""

    @staticmethod
    def render_qr(qr_data: str) -> None:
        """将 QR 码数据渲染为 ASCII 艺术到终端。"""
        if not qr_data:
            print("⚠️ 无 QR 码数据", file=sys.stderr)
            return
        try:
            qr = qrcode.QRCode()
            qr.add_data(qr_data)
            qr.print_ascii(out=sys.stderr)
        except Exception:
            print(f"请扫描: {qr_data}", file=sys.stderr)
