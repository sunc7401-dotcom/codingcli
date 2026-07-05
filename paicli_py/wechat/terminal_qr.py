"""终端 QR 码渲染器 —— 对应 com.paicli.wechat.TerminalQrRenderer。"""

import sys


def render_qr_terminal(qr_data: str) -> None:
    """在终端打印 QR 码（ASCII 艺术）。"""
    if not qr_data:
        print("⚠️ 无 QR 数据", file=sys.stderr)
        return
    try:
        import qrcode
        qr = qrcode.QRCode()
        qr.add_data(qr_data)
        qr.print_ascii(out=sys.stderr)
    except ImportError:
        print(f"请扫描: {qr_data}", file=sys.stderr)
