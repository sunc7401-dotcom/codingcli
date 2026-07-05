"""代码关系分析器 —— 提取 extends/implements/calls/contains 等关系。

对应 ``com.paicli.rag.CodeAnalyzer``。
使用 tree-sitter 进行 AST 分析。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeRelation:
    """代码关系记录。"""
    from_file: str
    from_name: str | None
    to_file: str
    to_name: str | None
    relation_type: str  # extends, implements, calls, contains, imports


class CodeAnalyzer:
    """代码关系分析器。

    对 Python 使用 ast 模块，对 Java 使用 tree-sitter（如可用），
    提取类/函数之间的依赖关系。
    """

    @classmethod
    def analyze(cls, file_path: Path) -> list[CodeRelation]:
        """分析单个文件的代码关系。"""
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return cls._analyze_python(file_path)
        elif suffix == ".java":
            return cls._analyze_java(file_path)
        return []

    @classmethod
    def _analyze_python(cls, file_path: Path) -> list[CodeRelation]:
        """Python AST 关系分析。"""
        try:
            import ast
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            return []

        relations: list[CodeRelation] = []
        rel_path = str(file_path)
        current_class: str | None = None

        for node in ast.walk(tree):
            # 类定义
            if isinstance(node, ast.ClassDef):
                current_class = node.name
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        relations.append(CodeRelation(
                            from_file=rel_path, from_name=node.name,
                            to_file=rel_path, to_name=base.id,
                            relation_type="extends",
                        ))
                # contains: 类包含方法
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.FunctionDef):
                        relations.append(CodeRelation(
                            from_file=rel_path, from_name=node.name,
                            to_file=rel_path, to_name=f"{node.name}.{child.name}",
                            relation_type="contains",
                        ))

            # 函数调用
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    relations.append(CodeRelation(
                        from_file=rel_path,
                        from_name=current_class,
                        to_file=rel_path,
                        to_name=node.func.id,
                        relation_type="calls",
                    ))
                elif isinstance(node.func, ast.Attribute):
                    relations.append(CodeRelation(
                        from_file=rel_path,
                        from_name=current_class,
                        to_file=rel_path,
                        to_name=node.func.attr,
                        relation_type="calls",
                    ))

            # 导入
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    relations.append(CodeRelation(
                        from_file=rel_path, from_name=None,
                        to_file=rel_path, to_name=alias.name,
                        relation_type="imports",
                    ))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    relations.append(CodeRelation(
                        from_file=rel_path, from_name=None,
                        to_file=rel_path, to_name=node.module,
                        relation_type="imports",
                    ))

        return relations

    @classmethod
    def _analyze_java(cls, file_path: Path) -> list[CodeRelation]:
        """Java 关系分析（降级为正则匹配）。"""
        import re

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        relations: list[CodeRelation] = []
        rel_path = str(file_path)

        # extends
        for m in re.finditer(r"class\s+(\w+)\s+extends\s+(\w+)", source):
            relations.append(CodeRelation(
                from_file=rel_path, from_name=m.group(1),
                to_file=rel_path, to_name=m.group(2),
                relation_type="extends",
            ))

        # implements
        for m in re.finditer(r"class\s+(\w+)\s+implements\s+([\w,\s]+)", source):
            for iface in re.findall(r"(\w+)", m.group(2)):
                relations.append(CodeRelation(
                    from_file=rel_path, from_name=m.group(1),
                    to_file=rel_path, to_name=iface,
                    relation_type="implements",
                ))

        return relations
