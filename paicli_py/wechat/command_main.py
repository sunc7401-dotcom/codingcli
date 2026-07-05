"""微信命令入口 —— 对应 ``com.paicli.wechat.WechatCommandMain``。"""

from __future__ import annotations

import asyncio

from loguru import logger


def run_wechat_command(args: list[str]) -> None:
    """处理 wechat 子命令（setup / start / status）。

    对应 Java WechatCommandMain.run(args)。
    """
    if not args:
        print("用法: paicli wechat <setup|start|status>")
        return

    subcommand = args[0].lower()

    if subcommand == "setup":
        asyncio.run(_wechat_setup())
    elif subcommand == "start":
        asyncio.run(_wechat_start())
    elif subcommand == "status":
        asyncio.run(_wechat_status())
    else:
        print(f"未知子命令: {subcommand}")
        print("用法: paicli wechat <setup|start|status>")


async def _wechat_setup() -> None:
    """微信设置：QR 码登录并保存账号。"""
    import datetime

    from paicli_py.wechat.account import WechatAccount
    from paicli_py.wechat.account_store import WechatAccountStore
    from paicli_py.wechat.client import IlinkClient
    from paicli_py.wechat.qr_login import WechatQrLogin

    client = IlinkClient()
    login = WechatQrLogin(client)
    result = await login.login()

    if result.success:
        account = WechatAccount(
            token=result.token,
            account_id=result.account_id,
            created_at=datetime.datetime.now().isoformat(),
        )
        WechatAccountStore.save(account)
        print(f"✅ 账号已保存: {account.account_id}")
    else:
        print(f"❌ 登录失败: {result.error}")


async def _wechat_start() -> None:
    """启动微信消息循环。"""
    from paicli_py.wechat.account_store import WechatAccountStore
    from paicli_py.wechat.client import IlinkClient
    from paicli_py.wechat.message_loop import WechatMessageLoop

    account = WechatAccountStore.load()
    if not account:
        print("❌ 未找到微信账号，请先运行: paicli wechat setup")
        return

    client = IlinkClient(base_url=account.base_url)
    client.set_token(account.token)
    loop = WechatMessageLoop(client)
    logger.info("微信消息循环已启动")
    await loop.run()


async def _wechat_status() -> None:
    """显示微信连接状态。"""
    from paicli_py.wechat.account_store import WechatAccountStore

    account = WechatAccountStore.load()
    if account:
        print(f"✅ 已登录: {account.account_id}")
        print(f"   工作区: {account.workspace or '(默认)'}")
    else:
        print("❌ 未登录，请运行: paicli wechat setup")
