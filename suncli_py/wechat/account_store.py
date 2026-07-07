"""微信账号持久化存储 —— 对应 ``com.paicli.wechat.WechatAccountStore``。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from suncli_py.wechat.account import WechatAccount


class WechatAccountStore:
    """将微信账号持久化到 ~/.paicli/wechat/accounts/latest.json。"""

    STORE_DIR = Path.home() / ".paicli" / "wechat" / "accounts"
    STORE_FILE = STORE_DIR / "latest.json"

    @classmethod
    def load(cls) -> WechatAccount | None:
        if not cls.STORE_FILE.is_file():
            return None
        try:
            data = json.loads(cls.STORE_FILE.read_text(encoding="utf-8"))
            return WechatAccount(
                token=data.get("token", ""),
                account_id=data.get("accountId", data.get("account_id", "")),
                base_url=data.get("baseUrl", data.get("base_url", "https://ilink.weixin.qq.com")),
                bound_user_id=data.get("boundUserId", data.get("bound_user_id", "")),
                workspace=data.get("workspace", ""),
                sync_buf=data.get("syncBuf", data.get("sync_buf", "")),
                created_at=data.get("createdAt", data.get("created_at", "")),
            )
        except (json.JSONDecodeError, KeyError):
            return None

    @classmethod
    def save(cls, account: WechatAccount) -> None:
        cls.STORE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "token": account.token,
            "accountId": account.account_id,
            "baseUrl": account.base_url,
            "boundUserId": account.bound_user_id,
            "workspace": account.workspace,
            "syncBuf": account.sync_buf,
            "createdAt": account.created_at,
        }
        cls.STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # POSIX 安全权限
        try:
            os.chmod(cls.STORE_FILE, 0o600)
        except OSError:
            pass
