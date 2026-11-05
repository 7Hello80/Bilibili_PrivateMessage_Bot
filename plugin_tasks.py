"""插件安装任务：后台线程执行 + 进度/日志轮询。

面板请求只负责创建任务并轮询状态，真正的下载/校验/解压/热加载在后台线程完成，
这样即使单个镜像长时间无响应，UI 也能实时看到进度与日志。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from github_source import github_source
from plugin_manage import plugin_manager

MAX_TASKS = 30           # 内存中保留的最近任务数
MAX_LOG_LINES = 600      # 单个任务保留的日志行数


class InstallCanceled(Exception):
    """用户取消安装。"""


class InstallTask:
    def __init__(self, repo_full_name: str, plugin_name: str):
        self.id = uuid.uuid4().hex[:12]
        self.repo_full_name = repo_full_name
        self.plugin_name = plugin_name
        self.status = "pending"     # pending | running | success | error | canceled
        self.progress = 0
        self.stage = "排队中"
        self.message = ""
        self.mirror = None
        self.logs: List[Dict[str, Any]] = []
        self.seq = 0
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.canceled = False
        self._lock = threading.Lock()

    # ---------- 状态更新 ----------

    def log(self, level: str, message: str) -> None:
        with self._lock:
            self.seq += 1
            self.logs.append({
                "seq": self.seq,
                "time": time.strftime("%H:%M:%S"),
                "level": str(level).upper(),
                "message": str(message),
            })
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[:len(self.logs) - MAX_LOG_LINES]

    def set_state(self, progress: Optional[int] = None, stage: Optional[str] = None,
                  status: Optional[str] = None, message: Optional[str] = None,
                  mirror: Optional[str] = None,
                  started_at: Optional[float] = None) -> None:
        with self._lock:
            if started_at is not None and self.started_at is None:
                self.started_at = started_at
            if progress is not None:
                self.progress = max(0, min(100, int(progress)))
            if stage is not None:
                self.stage = stage
            if status is not None:
                self.status = status
                if status in ("success", "error", "canceled"):
                    self.finished_at = time.time()
                    if self.started_at is None:
                        self.started_at = self.created_at
            if message is not None:
                self.message = message
            if mirror is not None:
                self.mirror = mirror

    def check_cancel(self) -> None:
        if self.canceled:
            raise InstallCanceled()

    def snapshot(self, since: int = 0, limit: int = 300) -> Dict[str, Any]:
        with self._lock:
            logs = [item for item in self.logs if item["seq"] > since]
            truncated = len(logs) > limit
            if truncated:
                logs = logs[-limit:]
            return {
                "id": self.id,
                "repo_full_name": self.repo_full_name,
                "plugin_name": self.plugin_name,
                "status": self.status,
                "progress": self.progress,
                "stage": self.stage,
                "message": self.message,
                "mirror": self.mirror,
                "canceled": self.canceled,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": logs,
                "log_cursor": self.seq,
                "log_truncated": truncated,
            }


_tasks: "OrderedDict[str, InstallTask]" = OrderedDict()
_tasks_lock = threading.Lock()


def _register(task: InstallTask) -> None:
    with _tasks_lock:
        _tasks[task.id] = task
        while len(_tasks) > MAX_TASKS:
            _, old = _tasks.popitem(last=False)
            if old.status in ("pending", "running"):
                # 理论上不会发生(最多 30 个并发任务)，保险起见放回去
                _tasks[old.id] = old
                break


def get_task(task_id: str, since: int = 0, limit: int = 300) -> Optional[Dict[str, Any]]:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        return None
    return task.snapshot(since=since, limit=limit)


def list_tasks(limit: int = 10, log_tail: int = 12) -> List[Dict[str, Any]]:
    """最近的任务（新→旧）。附带少量日志尾巴，便于页面刷新后恢复卡片内容。"""
    with _tasks_lock:
        tasks = list(_tasks.values())[-limit:]
    return [t.snapshot(limit=log_tail) for t in reversed(tasks)]


def cancel_task(task_id: str) -> bool:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None or task.status not in ("pending", "running"):
        return False
    task.canceled = True
    task.log("WARN", "收到取消请求，正在停止…")
    return True


# ---------------- 具体步骤 ----------------


def _fetch_remote_package(repo_full_name: str, log) -> Optional[Dict[str, Any]]:
    """读取远端 package.json(不计入失败: 仅用于日志展示与分支判断)。"""
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{repo_full_name}/{branch}/package.json"
        data, mirror, status = github_source.get_json("raw", url, log=log)
        if data is None:
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("_branch", branch)
        if mirror:
            log("INFO", f"读取 package.json 成功（源：{mirror['name']}，分支 {branch}）")
        name = data.get("name") or repo_full_name
        version = data.get("version") or "未知"
        log("INFO", f"远端插件：{name} v{version}")
        return data
    log("WARN", "未能读取远端 package.json（不影响安装，将继续下载）")
    return None


def _find_extracted_dir(temp_dir: str, repo_full_name: str) -> Optional[str]:
    repo_name = repo_full_name.split("/")[-1]
    for suffix in ("main", "master"):
        candidate = os.path.join(temp_dir, f"{repo_name}-{suffix}")
        if os.path.isdir(candidate):
            return candidate
    subdirs = [d for d in os.listdir(temp_dir)
               if os.path.isdir(os.path.join(temp_dir, d))]
    if len(subdirs) == 1:
        return os.path.join(temp_dir, subdirs[0])
    return None


def _format_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} GB"


def _run_install(task: InstallTask) -> None:
    log = task.log
    temp_dir = ""
    try:
        task.set_state(status="running", started_at=time.time(), progress=2, stage="校验插件信息")
        log("INFO", f"开始安装插件：{task.repo_full_name}")
        task.check_cancel()

        plugin_name = plugin_manager.sanitize_plugin_name(task.plugin_name)
        if not plugin_name:
            raise ValueError("插件名称不合法（仅允许字母、数字、下划线和连字符）")
        task.plugin_name = plugin_name
        log("INFO", f"插件目录名：{plugin_name}")

        # 1) 远端元数据
        task.set_state(progress=8, stage="读取仓库信息")
        package_info = _fetch_remote_package(task.repo_full_name, log)
        task.check_cancel()

        branch = (package_info or {}).get("_branch")
        branches = [branch] if branch else ["main", "master"]

        # 2) 下载压缩包（带换源与停滞检测）
        task.set_state(progress=18, stage="准备下载")
        temp_dir = tempfile.mkdtemp(prefix="plugin_install_")
        zip_path = os.path.join(temp_dir, f"{plugin_name}.zip")

        def on_progress(downloaded: int, total: int, speed: float) -> None:
            if task.canceled:
                return
            task.check_cancel()
            if total > 0:
                ratio = min(downloaded / total, 1.0)
                percent = 18 + int(ratio * 58)
                stage = (f"下载中 {_format_size(downloaded)} / {_format_size(total)}"
                         f" · {_format_size(speed)}/s")
            else:
                percent = 26
                stage = f"下载中 {_format_size(downloaded)} · {_format_size(speed)}/s"
            task.set_state(progress=percent, stage=stage)

        downloaded_ok = False
        used_source = None
        for branch_name in branches:
            url = f"https://github.com/{task.repo_full_name}/archive/refs/heads/{branch_name}.zip"
            log("INFO", f"下载分支 {branch_name} 的压缩包…")
            ok, used_source = github_source.download(url, zip_path, kind="zip", log=log, progress=on_progress)
            if ok:
                log("INFO", f"使用源：{used_source}")
                downloaded_ok = True
                break
            task.check_cancel()
        if not downloaded_ok:
            raise RuntimeError("下载失败：所有 GitHub 源均不可用")

        task.set_state(progress=78, stage="解压插件包", mirror=used_source)
        task.check_cancel()

        # 3) 安全解压
        if not plugin_manager._safe_extract_zip(zip_path, temp_dir):
            raise RuntimeError("解压失败：压缩包包含危险路径或已损坏")
        log("INFO", "压缩包解压完成")

        extracted_dir = _find_extracted_dir(temp_dir, task.repo_full_name)
        if not extracted_dir:
            raise RuntimeError("解压后未找到插件目录")

        # 4) 结构 + 语法校验
        task.set_state(progress=84, stage="校验插件结构与语法")
        error = plugin_manager._validate_downloaded_plugin(extracted_dir)
        if error:
            raise RuntimeError(f"插件校验失败：{error}")
        log("INFO", "结构校验与 main.py 语法检查通过（仅编译，不执行）")
        task.check_cancel()

        # 5) 写入插件目录
        task.set_state(progress=90, stage="写入插件目录")
        try:
            package_path = os.path.join(extracted_dir, "package.json")
            with open(package_path, "r", encoding="utf-8") as fh:
                package = json.load(fh)
            package.setdefault("repository", f"https://github.com/{task.repo_full_name}")
            with open(package_path, "w", encoding="utf-8") as fh:
                json.dump(package, fh, indent=4, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            log("WARN", f"补充 repository 字段失败（忽略）：{exc}")

        plugin_dir = os.path.join(plugin_manager.plugins_dir, plugin_name)
        if os.path.exists(plugin_dir):
            log("WARN", f"目标目录已存在，先移除旧版本：{plugin_name}")
            shutil.rmtree(plugin_dir)
        shutil.copytree(extracted_dir, plugin_dir)
        log("INFO", f"插件已写入 {plugin_dir}")

        # 6) 通知机器人热加载
        task.set_state(progress=95, stage="通知机器人加载")
        bot_notice = "机器人未运行，将在下次启动时加载"
        try:
            from plugin_bridge import get_bridge
            bridge_result = get_bridge().send_command("load", plugin_name, wait=True)
            if bridge_result.get("bot_running"):
                ok = bridge_result.get("executed", True) and \
                    (bridge_result.get("result") or {}).get("success", True)
                task.log("INFO" if ok else "WARN",
                         f"机器人热加载返回：{bridge_result.get('message', '无消息')}")
                bot_notice = "已通知机器人加载"
            else:
                log("WARN", "机器人未运行，插件将在下次启动时加载")
        except Exception as exc:  # noqa: BLE001
            log("WARN", f"通知机器人失败：{exc}")

        task.set_state(progress=100, stage="安装完成", status="success",
                       message=f"插件 {plugin_name} 安装成功（{bot_notice}）")
        log("INFO", f"安装完成：{plugin_name}")

    except InstallCanceled:
        task.set_state(status="canceled", stage="已取消", message="安装已取消")
        log("WARN", "安装已取消")
    except Exception as exc:  # noqa: BLE001
        task.set_state(status="error", stage="安装失败",
                       message=f"安装失败：{exc}")
        log("ERROR", f"安装失败：{exc}")
        logging_trace = traceback.format_exc(limit=3)
        for line in logging_trace.strip().splitlines()[-3:]:
            log("ERROR", line)
    finally:
        if temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass


def create_install_task(repo_full_name: str, plugin_name: str) -> Dict[str, Any]:
    task = InstallTask(repo_full_name, plugin_name)
    _register(task)
    thread = threading.Thread(target=_run_install, args=(task,),
                              name=f"plugin-install-{task.id}", daemon=True)
    thread.start()
    return task.snapshot()
