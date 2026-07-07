"""微信路径工具 —— 对应 ``com.paicli.wechat.WechatPaths``。"""

from pathlib import Path


class WechatPaths:
    ROOT = Path.home() / ".paicli" / "wechat"

    @classmethod
    def accounts_dir(cls) -> Path:
        return cls.ROOT / "accounts"

    @classmethod
    def workspace_dir(cls, account_id: str) -> Path:
        return cls.ROOT / "workspaces" / account_id
