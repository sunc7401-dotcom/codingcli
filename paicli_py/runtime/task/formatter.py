"""任务命令格式化器 —— 对应 ``com.paicli.runtime.task.TaskCommandFormatter``。"""

from __future__ import annotations

from paicli_py.runtime.task.manager import DurableTaskManager
from paicli_py.runtime.task.status import TaskStatus
from paicli_py.runtime.task.task import DurableTask


def handle(manager: DurableTaskManager, payload: str | None) -> str:
    """处理 /task 命令（与 Java TaskCommandFormatter.handle() 一致）。"""
    payload = (payload or "").strip()

    if not payload or payload == "list":
        return format_list(manager.list(20))
    parts = payload.split(maxsplit=1)

    if parts[0] == "list" and len(parts) > 1:
        try: n = int(parts[1]); return format_list(manager.list(n))
        except ValueError: return f"无效数量: {parts[1]}"

    elif parts[0] == "add" and len(parts) > 1:
        try: task = manager.enqueue(parts[1]); return f"✅ 任务已入队: {task.id}"
        except Exception as e: return f"❌ 入队失败: {e}"

    elif parts[0] == "cancel" and len(parts) > 1:
        ok = manager.cancel(parts[1])
        return f"{'✅ 已取消' if ok else '❌ 取消失败'}: {parts[1]}"

    elif parts[0] == "log" and len(parts) > 1:
        task = manager.find(parts[1])
        return format_log(task) if task else f"未找到任务: {parts[1]}"

    return "/task list [N] | add <内容> | cancel <id> | log <id>"


def format_list(tasks: list[DurableTask]) -> str:
    """格式化任务列表（纯文本，与 Java 一致）。"""
    if not tasks:
        return "(无任务)"

    lines: list[str] = []
    for i, task in enumerate(tasks, 1):
        duration = f"{task.duration_ms}ms" if task.duration_ms else "-"
        lines.append(f"  {i}. [{task.status.value}] {task.id} {duration} {task.short_prompt}")
    return "\n".join(lines)


def format_log(task: DurableTask) -> str:
    """格式化单个任务日志（含时间戳，与 Java 一致）。"""
    lines = [
        f"任务: {task.id}",
        f"状态: {task.status.value}",
        f"提示: {task.prompt}",
    ]
    if task.created_at: lines.append(f"创建: {task.created_at}")
    if task.started_at: lines.append(f"开始: {task.started_at}")
    if task.finished_at: lines.append(f"完成: {task.finished_at}")
    if task.result: lines.append(f"结果:\n{task.result}")
    if task.error: lines.append(f"错误: {task.error}")
    if task.duration_ms: lines.append(f"耗时: {task.duration_ms}ms")
    return "\n".join(lines)
