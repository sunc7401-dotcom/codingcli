"""侧 Git 管理器 —— 对应 ``com.paicli.snapshot.SideGitManager``。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from suncli_py.snapshot.config import SnapshotConfig
from suncli_py.snapshot.phase import SnapshotPhase
from suncli_py.snapshot.restore_result import RestoreResult
from suncli_py.snapshot.turn_snapshot import TurnSnapshot

SNAPSHOT_IDENT = "PaiCLI Snapshot <snapshot@paicli.local>"


class SideGitManager:
    """侧 Git 快照管理器。"""

    def __init__(self, project_path: str, config: SnapshotConfig | None = None) -> None:
        self._project_path = Path(project_path).resolve()
        self._config = config if config else SnapshotConfig
        self._git_dir = self._compute_git_dir()
        self._snapshots: list[TurnSnapshot] = []
        self._repo = None
        self._init_repo()

    def _compute_git_dir(self) -> Path:
        parent_key = self._config.project_key(str(self._project_path.parent))
        proj_key = self._config.project_key(str(self._project_path))
        return self._config.snapshots_root() / parent_key[:8] / proj_key[:8] / ".git"

    def _init_repo(self) -> None:
        try:
            from dulwich.repo import Repo
            if not self._git_dir.exists():
                self._git_dir.mkdir(parents=True, exist_ok=True)
                Repo.init_bare(str(self._git_dir))
            self._repo = Repo(str(self._git_dir))
        except (ImportError, Exception):
            self._repo = None

    def close(self) -> None:
        if self._repo:
            try: self._repo.close()
            except Exception: pass
            self._repo = None

    @property
    def git_dir(self) -> Path:
        return self._git_dir

    # ── 便捷快照方法 ─────────────────────────────────────

    def pre_turn_snapshot(self, turn_id: str, summary: str = "") -> TurnSnapshot | None:
        return self.create_snapshot(SnapshotPhase.PRE_TURN, turn_id, summary)

    def post_turn_snapshot(self, turn_id: str, summary: str = "") -> TurnSnapshot | None:
        return self.create_snapshot(SnapshotPhase.POST_TURN, turn_id, summary)

    def pre_restore_snapshot(self, turn_id: str, summary: str = "") -> TurnSnapshot | None:
        return self.create_snapshot(SnapshotPhase.PRE_RESTORE, turn_id, summary)

    def create_snapshot(self, phase: SnapshotPhase, turn_id: str, summary: str = "") -> TurnSnapshot | None:
        """创建快照（含 summary）。"""
        if self._repo is None:
            return None
        try:
            from dulwich.objects import Blob, Commit, Tree
            tree = Tree()
            for file_path in self._iter_project_files():
                try:
                    content = file_path.read_bytes()
                    blob = Blob.from_string(content)
                    self._repo.object_store.add_object(blob)
                    rel = str(file_path.relative_to(self._project_path)).replace("\\", "/")
                    tree.add(rel.encode("utf-8"), 0o100644, blob.id)
                except OSError:
                    continue
            self._repo.object_store.add_object(tree)
            commit = Commit()
            commit.tree = tree.id
            commit.author = SNAPSHOT_IDENT.encode("utf-8")
            commit.author_time = int(time.time())
            commit.author_timezone = 0
            commit.committer = commit.author
            commit.commit_time = commit.author_time
            commit.commit_timezone = 0
            msg = f"{phase.value} {turn_id}"
            if summary:
                msg += f"\n\n{summary}"
            commit.message = msg.encode("utf-8")
            if self._repo.refs.get(b"refs/heads/main"):
                commit.parents = [self._repo.refs[b"refs/heads/main"]]
            self._repo.object_store.add_object(commit)
            self._repo.refs[b"refs/heads/main"] = commit.id
            ts = TurnSnapshot(commit_id=commit.id.hex(), phase=phase, turn_id=turn_id, summary=summary)
            self._snapshots.append(ts)
            return ts
        except Exception:
            return None

    # ── 恢复 ─────────────────────────────────────────────

    def restore_pre_turn(self, offset: int = 1) -> RestoreResult:
        """恢复到第 N 个最近的 PRE_TURN 快照（1-based，与 Java 一致）。"""
        offset = max(1, offset)
        pre_turns = [s for s in self._snapshots if s.phase == SnapshotPhase.PRE_TURN]
        if offset < 1 or offset > len(pre_turns):
            return RestoreResult(success=False, error=f"序号 {offset} 超出范围 (共 {len(pre_turns)} 个)")
        target = pre_turns[offset - 1]
        # 恢复前先快照
        self.pre_restore_snapshot(f"restore-{target.turn_id}")
        return self.restore(SnapshotPhase.PRE_TURN, offset - 1)

    def restore(self, phase: SnapshotPhase, turn_index: int = -1) -> RestoreResult:
        if self._repo is None:
            return RestoreResult(success=False, error="快照仓库未初始化")
        matching = [s for s in self._snapshots if s.phase == phase]
        if not matching:
            return RestoreResult(success=False, error="无匹配快照")
        try:
            idx = turn_index if turn_index >= 0 else len(matching) + turn_index
            target = matching[idx]
        except IndexError:
            return RestoreResult(success=False, error="索引超出范围")
        try:
            target_commit = self._repo[target.commit_id.encode("utf-8")]
            target_tree = self._repo[target_commit.tree]
            restored: list[str] = []
            for entry in target_tree.items():
                if entry.mode != 0o100644: continue
                fp = self._project_path / entry.path.decode("utf-8")
                fp.parent.mkdir(parents=True, exist_ok=True)
                blob = self._repo[entry.sha]
                fp.write_bytes(blob.data)
                restored.append(str(fp.relative_to(self._project_path)))
            return RestoreResult(success=True, restored_files=restored, deleted_files=[])
        except Exception as e:
            return RestoreResult(success=False, error=str(e))

    # ── 查询 ─────────────────────────────────────────────

    def list_snapshots(self, limit: int = 50) -> list[TurnSnapshot]:
        return list(self._snapshots[-limit:])

    def format_status(self) -> str:
        enabled = "✅" if self._config.enabled() else "❌"
        status = "启用" if self._config.enabled() else "禁用"
        lines = [f"{enabled} 快照: {status}", f"   项目根: {self._project_path}",
                 f"   快照数: {len(self._snapshots)} (上限 {self._config.max_snapshots()})"]
        if self._snapshots:
            latest = self._snapshots[-1]
            lines.append(f"   最新: {latest.phase.value} {latest.turn_id}")
        return "\n".join(lines)

    def clean_snapshots(self) -> str:
        """清理快照目录，返回状态消息。"""
        import shutil
        repo_parent = self._git_dir.parent
        if repo_parent.exists():
            shutil.rmtree(str(repo_parent))
            self._snapshots.clear()
            self._repo = None
            return "快照目录已清理"
        return "快照目录不存在"

    # ── 内部 ─────────────────────────────────────────────

    def _iter_project_files(self):
        excludes = set(self._config.excludes())
        for dirpath, dirnames, filenames in os.walk(str(self._project_path)):
            dirnames[:] = [d for d in dirnames if d not in excludes and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."): continue
                skip = False
                for pat in excludes:
                    if "*" in pat:
                        from fnmatch import fnmatch
                        if fnmatch(fname, pat): skip = True; break
                if skip: continue
                yield Path(dirpath) / fname
