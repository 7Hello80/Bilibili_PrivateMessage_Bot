"""GitHub 加速源管理。

设计目标：
1. 默认直连 GitHub 官方源（github.com / raw.githubusercontent.com / api.github.com）；
2. 官方源长时间无响应（连接超时或读取停滞）时自动切换到加速镜像；
3. 支持手动指定镜像，或填写自定义前缀；
4. 记录每个源的运行健康度，供面板展示与排序。

说明：加速镜像统一采用「前缀 + 原始 URL」形式（如 https://ghfast.top/https://github.com/...），
API 请求无法这样代理，因此单独使用 api_base（如 api.kkgithub.com）。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

USER_AGENT = "BilibiliBot-Panel/2.0 (+plugin-installer)"

# connect: 建立连接超时；stall: 两次收到数据之间的最长间隔（长时间无响应判定）
DEFAULT_CONNECT_TIMEOUT = 6
DEFAULT_STALL_TIMEOUT = 12
# 官方源连续失败达到该次数后，在冷却期内临时排到队尾，避免每次都等超时
DEGRADE_FAILS = 2
DEGRADE_COOLDOWN = 300  # 秒

MIRRORS: List[Dict[str, str]] = [
    {
        "id": "official",
        "name": "GitHub 官方",
        "prefix": "",
        "api_base": "https://api.github.com",
        "note": "直连 github.com / raw.githubusercontent.com，无第三方中转",
    },
    {
        "id": "ghfast",
        "name": "ghfast.top",
        "prefix": "https://ghfast.top/",
        "api_base": "",
        "note": "社区加速，支持仓库压缩包与 raw 文件",
    },
    {
        "id": "ghproxy_net",
        "name": "ghproxy.net",
        "prefix": "https://ghproxy.net/",
        "api_base": "",
        "note": "社区加速，支持仓库压缩包与 raw 文件",
    },
    {
        "id": "gh_proxy",
        "name": "gh-proxy.com",
        "prefix": "https://gh-proxy.com/",
        "api_base": "",
        "note": "社区加速，支持仓库压缩包与 raw 文件",
    },
    {
        "id": "ghproxy_cc",
        "name": "ghproxy.cc",
        "prefix": "https://ghproxy.cc/",
        "api_base": "",
        "note": "社区加速，支持仓库压缩包与 raw 文件",
    },
    {
        "id": "llkk",
        "name": "gh.llkk.cc",
        "prefix": "https://gh.llkk.cc/",
        "api_base": "",
        "note": "社区加速，支持仓库压缩包与 raw 文件",
    },
    {
        "id": "jsdelivr",
        "name": "jsDelivr（仅 raw）",
        "prefix": "",
        "api_base": "",
        "note": "CDN 方式读取 raw 文件，不支持仓库压缩包",
    },
    {
        "id": "kkgithub",
        "name": "kkgithub（仅 API）",
        "prefix": "",
        "api_base": "https://api.kkgithub.com",
        "note": "GitHub API 镜像，用于搜索与版本检查",
    },
]

MIRROR_INDEX = {m["id"]: m for m in MIRRORS}
CUSTOM_ID = "custom"

DEFAULT_SETTINGS = {
    "mode": "auto",           # auto | manual
    "mirror": "official",     # manual 模式下的源 id
    "custom_prefix": "",      # 自定义前缀，形如 https://my-proxy.com/
    "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
    "stall_timeout": DEFAULT_STALL_TIMEOUT,
}


def _normalize_prefix(prefix: str) -> str:
    """把用户填写的自定义前缀规范化为以 / 结尾的形式。"""
    prefix = str(prefix or "").strip()
    if not prefix:
        return ""
    if not prefix.lower().startswith(("http://", "https://")):
        return ""
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


class GitHubSource:
    """负责把 GitHub 原始 URL 按当前策略映射到可用源，并执行请求/下载。"""

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        # RLock：_score() 在持锁状态下会调用 _is_degraded()，普通 Lock 会自锁
        self._lock = threading.RLock()
        self._health: Dict[str, Dict[str, Any]] = {}
        self._last_used: Optional[str] = None
        self._settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.reload()

    # ---------------- 配置 ----------------

    def reload(self) -> None:
        cfg: Dict[str, Any] = {}
        if self.config_manager is not None:
            try:
                cfg = self.config_manager.get_github_source() or {}
            except Exception:
                cfg = {}
        merged = dict(DEFAULT_SETTINGS)
        if isinstance(cfg, dict):
            for key in ("mode", "mirror", "custom_prefix"):
                if cfg.get(key) is not None:
                    merged[key] = cfg[key]
            for key in ("connect_timeout", "stall_timeout"):
                try:
                    value = float(cfg.get(key))
                    if value > 0:
                        merged[key] = value
                except (TypeError, ValueError):
                    pass
        if merged["mode"] not in ("auto", "manual"):
            merged["mode"] = "auto"
        if merged["mirror"] not in MIRROR_INDEX and merged["mirror"] != CUSTOM_ID:
            merged["mirror"] = "official"
        merged["custom_prefix"] = _normalize_prefix(merged.get("custom_prefix", ""))
        # 官方源不允许被长时间丢弃，兜底保存在列表里
        with self._lock:
            self._settings = merged

    def settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def update_settings(self, mode: Optional[str] = None, mirror: Optional[str] = None,
                        custom_prefix: Optional[str] = None,
                        connect_timeout: Optional[float] = None,
                        stall_timeout: Optional[float] = None,
                        persist: bool = True) -> Dict[str, Any]:
        with self._lock:
            cfg = dict(self._settings)
        if mode in ("auto", "manual"):
            cfg["mode"] = mode
        if mirror is not None:
            if mirror in MIRROR_INDEX or mirror == CUSTOM_ID:
                cfg["mirror"] = mirror
            elif mirror:
                raise ValueError("未知的加速源")
        if custom_prefix is not None:
            raw = str(custom_prefix).strip()
            if raw and not _normalize_prefix(raw):
                raise ValueError("自定义前缀必须以 http:// 或 https:// 开头")
            cfg["custom_prefix"] = _normalize_prefix(raw)
        for key, value in (("connect_timeout", connect_timeout),
                           ("stall_timeout", stall_timeout)):
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 120:
                cfg[key] = number
        with self._lock:
            self._settings = cfg
        if persist and self.config_manager is not None:
            try:
                self.config_manager.update_github_source(cfg)
            except Exception:
                pass
        return self.settings()

    # ---------------- 健康度 ----------------

    def _health_entry(self, mirror_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._health.setdefault(mirror_id, {
                "ok": 0, "fail": 0, "fails_in_row": 0,
                "latency": None, "last_ok": 0.0, "last_fail": 0.0,
                "last_error": "", "last_status": None,
            })

    def _mark_ok(self, mirror_id: str, latency: float, status: int = 200) -> None:
        entry = self._health_entry(mirror_id)
        with self._lock:
            entry["ok"] += 1
            entry["fails_in_row"] = 0
            entry["latency"] = round(latency, 3)
            entry["last_ok"] = time.time()
            entry["last_status"] = status
            entry["last_error"] = ""

    def _mark_fail(self, mirror_id: str, error: str) -> None:
        entry = self._health_entry(mirror_id)
        with self._lock:
            entry["fail"] += 1
            entry["fails_in_row"] += 1
            entry["last_fail"] = time.time()
            entry["last_error"] = str(error)[:200]
            self._last_used = mirror_id if self._last_used is None else self._last_used

    def _is_degraded(self, mirror_id: str) -> bool:
        entry = self._health_entry(mirror_id)
        with self._lock:
            return (entry["fails_in_row"] >= DEGRADE_FAILS and
                    (time.time() - entry["last_fail"]) < DEGRADE_COOLDOWN)

    def _score(self, mirror_id: str) -> int:
        entry = self._health_entry(mirror_id)
        with self._lock:
            if entry["last_ok"] and not self._is_degraded(mirror_id):
                return 3
            if not entry["last_ok"] and not entry["last_fail"]:
                return 2
            if self._is_degraded(mirror_id):
                return 0
            return 1

    # ---------------- 源选择 ----------------

    def custom_mirror(self) -> Optional[Dict[str, str]]:
        prefix = self.settings().get("custom_prefix") or ""
        if not prefix:
            return None
        return {
            "id": CUSTOM_ID,
            "name": "自定义前缀",
            "prefix": prefix,
            "api_base": "",
            "note": prefix,
        }

    def candidates(self, kind: str = "zip") -> List[Dict[str, str]]:
        """按当前策略返回有序候选源列表。kind: zip | raw | api"""
        settings = self.settings()
        if kind == "api":
            api_mirrors = [m for m in MIRRORS if m.get("api_base")]
            # 官方优先，其余 API 镜像按健康度排序
            official = [m for m in api_mirrors if m["id"] == "official"]
            others = [m for m in api_mirrors if m["id"] != "official"]
            others.sort(key=lambda m: self._score(m["id"]), reverse=True)
            return official + others

        if settings["mode"] == "manual":
            if settings["mirror"] == CUSTOM_ID:
                custom = self.custom_mirror()
                return [custom] if custom else []
            mirror = MIRROR_INDEX.get(settings["mirror"], MIRROR_INDEX["official"])
            return [mirror]

        # auto: 官方优先；连续失败后临时降级到队尾
        others = [m for m in MIRRORS if m["id"] != "official"]
        others.sort(key=lambda m: self._score(m["id"]), reverse=True)
        official = MIRROR_INDEX["official"]
        if self._is_degraded("official"):
            return others + [official]
        return [official] + others

    def _rewrite(self, mirror: Dict[str, str], kind: str, url: str) -> Optional[str]:
        mirror_id = mirror["id"]
        if kind == "api":
            base = mirror.get("api_base")
            if not base or not url.startswith("https://api.github.com"):
                return None
            return mirror["api_base"] + url[len("https://api.github.com"):]

        if mirror_id == "jsdelivr":
            if kind != "raw" or not url.startswith("https://raw.githubusercontent.com/"):
                return None
            rest = url[len("https://raw.githubusercontent.com/"):]
            parts = rest.split("/", 3)
            if len(parts) < 3:
                return None
            owner, repo, branch = parts[0], parts[1], parts[2]
            path = parts[3] if len(parts) > 3 else ""
            return f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}"

        prefix = mirror.get("prefix") or ""
        if prefix:
            return prefix + url
        return url

    # ---------------- 请求 ----------------

    def _timeouts(self) -> Tuple[float, float]:
        settings = self.settings()
        return (float(settings["connect_timeout"]), float(settings["stall_timeout"]))

    def request(self, kind: str, url: str, method: str = "GET",
                params: Optional[Dict[str, Any]] = None,
                headers: Optional[Dict[str, str]] = None,
                timeout: Optional[Tuple[float, float]] = None,
                stream: bool = False,
                log: Optional[Callable[[str, str], None]] = None) -> Tuple[Optional[requests.Response], Optional[Dict[str, str]]]:
        """按策略逐个尝试候选源，返回 (response, 命中源)。404/403 视为有效响应不切源。"""
        req_headers = {"User-Agent": USER_AGENT}
        if headers:
            req_headers.update(headers)
        connect_timeout, stall_timeout = timeout or self._timeouts()
        errors: List[str] = []

        for mirror in self.candidates(kind):
            target = self._rewrite(mirror, kind, url)
            if not target:
                continue
            started = time.monotonic()
            try:
                resp = requests.request(method, target, params=params, headers=req_headers,
                                        timeout=(connect_timeout, stall_timeout),
                                        stream=stream, allow_redirects=True)
            except requests.RequestException as exc:
                self._mark_fail(mirror["id"], str(exc))
                errors.append(f"{mirror['name']}: {exc}")
                if log:
                    log("WARN", f"{mirror['name']} 无响应（{self._friendly_error(exc)}），尝试下一个源")
                continue

            latency = time.monotonic() - started
            if resp.status_code < 400:
                self._mark_ok(mirror["id"], latency, resp.status_code)
                self._last_used = mirror["id"]
                if log and mirror["id"] != "official":
                    log("INFO", f"已通过加速源 {mirror['name']} 访问 GitHub（{latency * 1000:.0f} ms）")
                return resp, mirror

            if resp.status_code in (401, 403, 404):
                # 源本身可用，是资源/权限问题，不再换源
                self._mark_ok(mirror["id"], latency, resp.status_code)
                self._last_used = mirror["id"]
                return resp, mirror

            resp.close()
            self._mark_fail(mirror["id"], f"HTTP {resp.status_code}")
            errors.append(f"{mirror['name']}: HTTP {resp.status_code}")
            if log:
                log("WARN", f"{mirror['name']} 返回 HTTP {resp.status_code}，尝试下一个源")

        if log and errors:
            log("ERROR", "所有 GitHub 源均不可用：" + "；".join(errors[:3]))
        return None, None

    def get_json(self, kind: str, url: str, params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None,
                 log: Optional[Callable[[str, str], None]] = None,
                 timeout: Optional[Tuple[float, float]] = None
                 ) -> Tuple[Optional[Any], Optional[Dict[str, str]], Optional[int]]:
        resp, mirror = self.request(kind, url, params=params, headers=headers,
                                    timeout=timeout, log=log)
        if resp is None:
            return None, None, None
        try:
            status = resp.status_code
            if status != 200:
                return None, mirror, status
            return resp.json(), mirror, status
        except ValueError:
            return None, mirror, resp.status_code
        finally:
            resp.close()

    # ---------------- 下载 ----------------

    def download(self, url: str, dest_path: str, kind: str = "zip",
                 log: Optional[Callable[[str, str], None]] = None,
                 progress: Optional[Callable[[int, int, float], None]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Tuple[bool, Optional[str]]:
        """流式下载到 dest_path，带停滞检测；失败自动换源。返回 (成功, 源 id)。"""
        connect_timeout, stall_timeout = self._timeouts()
        req_headers = {"User-Agent": USER_AGENT}
        if headers:
            req_headers.update(headers)
        tmp_path = dest_path + ".part"
        last_error = ""

        for mirror in self.candidates(kind):
            target = self._rewrite(mirror, kind, url)
            if not target:
                continue
            self._cleanup(tmp_path)
            started = time.monotonic()
            try:
                with requests.get(target, headers=req_headers, stream=True, allow_redirects=True,
                                  timeout=(connect_timeout, stall_timeout)) as resp:
                    if resp.status_code != 200:
                        raise IOError(f"HTTP {resp.status_code}")
                    total = 0
                    try:
                        total = int(resp.headers.get("Content-Length") or 0)
                    except (TypeError, ValueError):
                        total = 0

                    downloaded = 0
                    window_start = time.monotonic()
                    window_bytes = 0
                    last_report = 0.0
                    with open(tmp_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if not chunk:
                                continue
                            fh.write(chunk)
                            downloaded += len(chunk)
                            now = time.monotonic()
                            if progress and (now - last_report) >= 0.25:
                                elapsed = max(now - window_start, 0.001)
                                speed = (downloaded - window_bytes) / elapsed
                                progress(downloaded, total, speed)
                                window_start, window_bytes = now, downloaded
                                last_report = now
                    if downloaded == 0:
                        raise IOError("响应为空")

                os.replace(tmp_path, dest_path)
                self._mark_ok(mirror["id"], time.monotonic() - started, 200)
                self._last_used = mirror["id"]
                if progress:
                    progress(downloaded, total or downloaded, 0.0)
                if log:
                    size_kb = downloaded / 1024.0
                    if mirror["id"] == "official":
                        log("INFO", f"下载完成：{size_kb:.1f} KB（GitHub 官方源）")
                    else:
                        log("INFO", f"下载完成：{size_kb:.1f} KB（加速源 {mirror['name']}）")
                return True, mirror["id"]

            except (requests.RequestException, IOError, OSError) as exc:
                last_error = str(exc)
                self._mark_fail(mirror["id"], last_error)
                self._cleanup(tmp_path)
                if log:
                    log("WARN", f"{mirror['name']} 下载中断（{self._friendly_error(exc)}），尝试下一个源")
                continue

        self._cleanup(tmp_path)
        if log:
            log("ERROR", f"下载失败，所有源均不可用：{last_error or '未知错误'}")
        return False, None

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc)
        lowered = text.lower()
        if "read timed out" in lowered or "readtimeout" in lowered:
            return "长时间无响应"
        if "connect" in lowered and "timed out" in lowered:
            return "连接超时"
        if "connection reset" in lowered or "remotedisconnected" in lowered:
            return "连接被重置"
        if "name or service not known" in lowered or "temporary failure in name resolution" in lowered:
            return "域名解析失败"
        return text[:80]

    @staticmethod
    def _cleanup(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ---------------- 测速 ----------------

    PROBE_URL = "https://raw.githubusercontent.com/octocat/Hello-World/master/README"

    def _probe_one(self, mirror: Dict[str, str], timeout: float = 8.0) -> Dict[str, Any]:
        target = self._rewrite(mirror, "raw", self.PROBE_URL)
        result = {
            "id": mirror["id"],
            "name": mirror["name"],
            "note": mirror.get("note", ""),
            "supported": target is not None,
            "ok": False,
            "latency": None,
            "error": "",
        }
        if not target:
            result["error"] = "不支持 raw 探测"
            return result
        started = time.monotonic()
        try:
            with requests.get(target, headers={"User-Agent": USER_AGENT}, stream=True,
                              timeout=(min(timeout, 6), timeout)) as resp:
                if resp.status_code != 200:
                    result["error"] = f"HTTP {resp.status_code}"
                    return result
                first = next(resp.iter_content(chunk_size=1024), b"")
                latency = time.monotonic() - started
                if not first:
                    result["error"] = "响应为空"
                    return result
                result["ok"] = True
                result["latency"] = round(latency, 3)
                self._mark_ok(mirror["id"], latency, 200)
        except requests.RequestException as exc:
            result["error"] = self._friendly_error(exc)
            self._mark_fail(mirror["id"], str(exc))
        return result

    def probe(self, timeout: float = 8.0) -> List[Dict[str, Any]]:
        """并发测速（仅探测 raw 文件首字节延迟），返回每个源的结果。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        candidates = [m for m in MIRRORS if self._rewrite(m, "raw", self.PROBE_URL)]
        custom = self.custom_mirror()
        if custom and self._rewrite(custom, "raw", self.PROBE_URL):
            candidates.append(custom)

        results: List[Dict[str, Any]] = []
        if not candidates:
            return results
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            futures = {pool.submit(self._probe_one, m, timeout): m for m in candidates}
            try:
                for future in as_completed(futures, timeout=timeout + 12):
                    try:
                        results.append(future.result())
                    except Exception as exc:  # noqa: BLE001
                        mirror = futures[future]
                        results.append({
                            "id": mirror["id"], "name": mirror["name"], "note": mirror.get("note", ""),
                            "supported": True, "ok": False, "latency": None,
                            "error": self._friendly_error(exc),
                        })
            except Exception:
                for future, mirror in futures.items():
                    if not future.done():
                        results.append({
                            "id": mirror["id"], "name": mirror["name"], "note": mirror.get("note", ""),
                            "supported": True, "ok": False, "latency": None, "error": "探测超时",
                        })
        order = {m["id"]: idx for idx, m in enumerate(MIRRORS)}
        results.sort(key=lambda item: order.get(item["id"], 99))
        return results

    # ---------------- 状态 ----------------

    def status(self) -> Dict[str, Any]:
        settings = self.settings()
        health = {}
        with self._lock:
            for mirror_id, entry in self._health.items():
                health[mirror_id] = dict(entry)
        mirrors = []
        for mirror in MIRRORS:
            item = {k: mirror[k] for k in ("id", "name", "note")}
            item["supports_zip"] = mirror["id"] != "jsdelivr"
            item["supports_api"] = bool(mirror.get("api_base"))
            item["health"] = health.get(mirror["id"], {})
            mirrors.append(item)
        custom = self.custom_mirror()
        if custom:
            mirrors.append({
                "id": CUSTOM_ID, "name": custom["name"], "note": custom["note"],
                "supports_zip": True, "supports_api": False,
                "health": health.get(CUSTOM_ID, {}),
            })
        effective = None
        if settings["mode"] == "manual":
            effective = settings["mirror"]
        elif self._is_degraded("official"):
            ordered = self.candidates("zip")
            effective = ordered[0]["id"] if ordered else "official"
        else:
            effective = "official"
        return {
            "settings": settings,
            "effective": effective,
            "last_used": self._last_used,
            "mirrors": mirrors,
        }


    def bind_config(self, config_manager) -> None:
        """面板启动后注入配置管理器（避免模块导入期循环依赖）。"""
        self.config_manager = config_manager
        self.reload()


github_source = GitHubSource()
