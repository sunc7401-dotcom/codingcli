"""代码关系模型 —— 对应 com.paicli.rag.CodeRelation。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeRelation:
    from_file: str
    from_name: str | None
    to_file: str
    to_name: str | None
    relation_type: str  # extends / implements / calls / contains / imports
