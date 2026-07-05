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
        """Java 关系分析（正则提取 5 种关系：imports/extends/implements/calls/contains）。"""
        import re

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        relations: list[CodeRelation] = []
        rel_path = str(file_path)
        current_class: str | None = None

        # imports
        for m in re.finditer(r"^import\s+(?:static\s+)?([\w.]+)\.(\w+)\s*;", source, re.MULTILINE):
            relations.append(CodeRelation(
                from_file=rel_path, from_name=None,
                to_file=rel_path, to_name=m.group(2),
                relation_type="imports",
            ))

        # extends + current_class tracking
        for m in re.finditer(r"class\s+(\w+)\s+extends\s+(\w+)", source):
            current_class = m.group(1)
            relations.append(CodeRelation(
                from_file=rel_path, from_name=m.group(1),
                to_file=rel_path, to_name=m.group(2),
                relation_type="extends",
            ))
        # class without extends
        if current_class is None:
            m = re.search(r"class\s+(\w+)", source)
            if m: current_class = m.group(1)

        # implements
        for m in re.finditer(r"class\s+\w+\s+implements\s+([\w,\s<>]+?)\s*\{", source):
            raw = re.sub(r"<[^>]+>", "", m.group(1))
            for iface in re.findall(r"(\w+)", raw):
                relations.append(CodeRelation(
                    from_file=rel_path, from_name=current_class,
                    to_file=rel_path, to_name=iface,
                    relation_type="implements",
                ))

        # contains: methods declared in class
        if current_class:
            for m in re.finditer(r"(?:public|private|protected|static|\s)+([\w<>,\[\]\s]+)\s+(\w+)\s*\([^)]*\)\s*(?:\{|throws)", source):
                method_name = m.group(2)
                if method_name == current_class: continue  # constructor
                relations.append(CodeRelation(
                    from_file=rel_path, from_name=current_class,
                    to_file=rel_path, to_name=f"{current_class}.{method_name}",
                    relation_type="contains",
                ))

        # calls: method invocations (skip java keywords)
        _keywords = {"if","for","while","switch","return","throw","new","try","catch","finally","synchronized","assert"}
        for m in re.finditer(r"(?:(\w+)\.)?(\w+)\s*\(", source):
            obj = m.group(1)
            called = m.group(2)
            if not called or called[0].islower() or called in _keywords:
                continue
            if obj:
                relations.append(CodeRelation(
                    from_file=rel_path, from_name=current_class,
                    to_file=rel_path, to_name=f"{obj}.{called}",
                    relation_type="calls",
                ))
            elif called and called[0].isupper():
                relations.append(CodeRelation(
                    from_file=rel_path, from_name=current_class,
                    to_file=rel_path, to_name=called,
                    relation_type="calls",
                ))

        return relations
