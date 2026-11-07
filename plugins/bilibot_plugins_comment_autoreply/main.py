# -*- coding: utf-8 -*-
"""
评论区 AI 自动回复插件
========================================
定时扫描配置的视频 / 动态 / 专栏评论区，也可以扫描「回复我的」评论消息，
把 @ 我 / 回复我的新评论交给大模型生成回复并发送。

功能
----
- 支持多个评论区（视频 BV/av、动态、专栏），每个评论区可指定账号
- 支持不配置评论区，直接从消息中心「回复我的」中扫描 @ 我 / 回复我的评论
- 首次扫描只记录基线，不会把历史评论全部回复一遍（可配置）
- 支持关键词过滤、仅回复 @UP、忽略用户、用户冷却、每日限额、单次扫描上限
- 支持 dry_run（只生成记录不发送），方便先观察效果
- OpenAI 兼容接口：DeepSeek / 通义 / Kimi / 智谱 / Ollama / One-API / OpenAI
- 面板接口：配置读写、连接测试、立即扫描、统计、回复记录、重置基线
- 私信命令：!comment_status / !comment_scan

API 文档来自 bilibili-API-collect：
- 评论列表: GET https://api.bilibili.com/x/v2/reply
- 发表评论: POST https://api.bilibili.com/x/v2/reply/add
- 回复我的消息: GET https://api.bilibili.com/x/msgfeed/reply
- 评论类型: 1 视频 / 12 专栏 / 17 动态

面板访问前缀: /api/plugins/api/bilibot_plugins_comment_autoreply
"""
import collections
import json
import os
import queue
import re
import threading
import time

import plugin_dev

DEFAULT_SYSTEM_PROMPT = (
    "你是 B 站 UP 主的评论区助理，替 UP 主回复视频/动态/专栏下的评论。"
    "请用自然、真诚、口语化的中文回答，一般不超过 80 字，不要用营销腔，"
    "不要编造 UP 主没有说过的事实，也不要承诺任何无法兑现的事情。"
    "遇到争议、敏感或你无法确认的问题，就礼貌说明会让 UP 主本人来回复。"
    "只输出回复正文，不要加引号，不要解释。"
)

DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 300,
        "timeout": 45,
        "max_reply_chars": 150,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    },
    "comment": {
        "enabled": False,
        "dry_run": True,
        "poll_interval_seconds": 120,
        "send_interval_seconds": 8,
        "videos": [],
        "message_feed": False,
        "accounts": [],
        "only_mention": False,
        "trigger_keywords": [],
        "ignore_keywords": [],
        "ignore_uids": [],
        "keyword_rules": [],
        "keyword_only": False,
        "cooldown_seconds": 60,
        "max_replies_per_day": 100,
        "max_replies_per_scan": 20,
        "max_pages_per_scan": 2,
        "max_comment_age_seconds": 604800,
        "reply_on_first_scan": False,
        "prefix_at": False,
        "fallback_reply": "",
    },
}

COMMENT_URL = "https://api.bilibili.com/x/v2/reply"
ADD_COMMENT_URL = "https://api.bilibili.com/x/v2/reply/add"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
MSG_REPLY_URL = "https://api.bilibili.com/x/msgfeed/reply"
# 「@我的」是独立接口：纯 @ 通知不会出现在 x/msgfeed/reply 里，
# 只扫 reply 会漏掉大量评论里的 @（实测 reply=0 而 at=1）
MSG_AT_URL = "https://api.bilibili.com/x/msgfeed/at"
MSG_UNREAD_URL = "https://api.bilibili.com/x/msgfeed/unread"
# 消息接口原始返回的调试落盘位置（相对项目根目录，.tmp 已在 .gitignore 中）
MSGFEED_DEBUG_PATH = os.path.join(".tmp", "msgfeed_debug.txt")
MSGFEED_DEBUG_LIMIT = 512 * 1024   # 单文件上限，超出后重新开始写

COMMENT_TYPE_NAMES = {1: "视频", 12: "专栏", 17: "动态"}

# 发送评论接口常见错误码
REPLY_ERRORS = {
    -101: "账号未登录，请检查 SESSDATA 是否过期",
    -102: "账号被封停",
    -111: "CSRF 校验失败，请检查 bili_jct",
    -400: "请求错误",
    -404: "无此项",
    -509: "请求过于频繁，请调大发送间隔",
    -352: "触发风控，请稍后再试",
    12001: "已经存在评论主题",
    12002: "评论区已关闭",
    12003: "禁止回复",
    12006: "没有该评论",
    12009: "评论主体的 type 不合法",
    12015: "需要评论验证码",
    12016: "评论内容包含敏感信息",
    12025: "评论字数过多",
    12035: "该账号被 UP 主列入评论黑名单",
    12051: "重复评论，请勿刷屏",
    12052: "评论区已关闭",
    12045: "购买后即可发表评论",
}

MAX_QUEUE_SIZE = 500
MAX_HISTORY_ROWS = 5000
MAX_VIDEOS = 50
SEEN_RETENTION_SECONDS = 30 * 24 * 3600


class LLMError(Exception):
    """大模型调用异常"""


class CommentError(Exception):
    """评论接口异常"""


class Plugin(plugin_dev.APIPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.2.1"

        self._stats = {
            "ai_calls": 0,
            "scanned": 0,
            "baseline": 0,
            "queued": 0,
            "replies_sent": 0,
            "failed": 0,
            "skipped": 0,
            "keyword_replies": 0,
        }
        self._last_error = ""
        self._last_scan_at = 0
        self._last_send_at = 0
        self._last_scan_tried = 0
        self._last_scan_duration = 0
        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._stop = threading.Event()
        self._worker = None
        self._poller = None
        self._scan_lock = threading.Lock()
        self._cooldown = {}          # uid -> 上次回复时间戳（内存加速，DB 为准）
        self._lock = threading.Lock()
        self._video_cache = {}
        self._ai_fallback_cache = (0, {})
        # 扫描日志（内存滚动保存，供面板「扫描日志」展示排查漏回复问题）
        self._scan_logs = collections.deque(maxlen=500)
        self._scan_log_lock = threading.Lock()

        # 已处理的评论（基线 + 已回复/已跳过），防止重复处理
        self.database.create_table("comment_seen", {
            "key": "TEXT PRIMARY KEY",
            "created_at": "REAL",
        })
        # 每个评论区的扫描状态（首次扫描基线时间）
        self.database.create_table("comment_scan_state", {
            "key": "TEXT PRIMARY KEY",
            "baseline_at": "REAL",
            "last_scan_at": "REAL",
        })
        # 回复记录
        self.database.create_table("comment_reply_log", {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "account": "TEXT",
            "type": "INTEGER",
            "oid": "TEXT",
            "title": "TEXT",
            "rpid": "TEXT",
            "mid": "TEXT",
            "uname": "TEXT",
            "question": "TEXT",
            "answer": "TEXT",
            "model": "TEXT",
            "latency_ms": "INTEGER",
            "ok": "INTEGER",
            "note": "TEXT",
            "created_at": "REAL",
        })

        self.register_command("comment_status", self.cmd_status, "查看评论区自动回复状态")
        self.register_command("comment_scan", self.cmd_scan, "立即扫描一次评论区")

        self.register_api_route("/config", self.api_config)
        self.register_api_route("/config/save", self.api_config_save, methods=["POST"])
        self.register_api_route("/ai/test", self.api_test, methods=["POST"])
        self.register_api_route("/stats", self.api_stats)
        self.register_api_route("/history", self.api_history)
        self.register_api_route("/history/clear", self.api_history_clear, methods=["POST"])
        self.register_api_route("/scan", self.api_scan, methods=["POST"])
        self.register_api_route("/seen/clear", self.api_seen_clear, methods=["POST"])
        self.register_api_route("/logs", self.api_logs)
        self.register_api_route("/logs/clear", self.api_logs_clear, methods=["POST"])

        self.register_metric("replies_sent", lambda: self._stats["replies_sent"])
        self.register_metric("failed", lambda: self._stats["failed"])
        self.register_metric("scanned", lambda: self._stats["scanned"])

    # ================= 生命周期 =================

    def on_load(self):
        self._prune_seen()
        cfg = self._comment_cfg()
        llm = self._llm_cfg()
        self._start_threads()
        if not llm.get("api_key") and not self._looks_local(llm.get("base_url")):
            self.logger.warning("尚未配置大模型 API Key，评论回复不可用（可在面板「评论自动回复」中配置）")
        if not cfg.get("enabled"):
            self.logger.info("评论区自动回复处于关闭状态（可在面板开启）")
        else:
            videos = self._normalise_videos(cfg.get("videos"))
            feed = self._bool(cfg.get("message_feed"))
            self.logger.info(
                "评论区自动回复已启用: 评论区=%s, 评论消息=%s, 间隔=%ss, 冷却=%ss, 每日上限=%s, dry_run=%s" % (
                    len(videos), "开" if feed else "关", cfg.get("poll_interval_seconds"),
                    cfg.get("cooldown_seconds"), cfg.get("max_replies_per_day"),
                    cfg.get("dry_run")))
            if not videos and not feed:
                self.logger.warning(
                    "已开启评论区自动回复，但既没有配置评论区，也没有开启评论消息扫描")

    def on_unload(self):
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        for thread in (self._worker, self._poller):
            if thread and thread.is_alive():
                thread.join(timeout=3)
        self._worker = None
        self._poller = None
        self.logger.info("评论区自动回复插件已卸载")

    # ================= 配置 =================

    @staticmethod
    def _p(data, key, default=None):
        if isinstance(data, dict):
            value = data.get(key, default)
            if value is not None:
                return value
        return default

    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on", "是"):
            return True
        if text in ("0", "false", "no", "off", "否", ""):
            return False
        return default

    @staticmethod
    def _keyword_list(value):
        """支持列表或分号/逗号/换行分隔的字符串"""
        if isinstance(value, (list, tuple)):
            items = [str(v).strip() for v in value]
        else:
            items = [v.strip() for v in re.split(r"[;；,，\n]", str(value or ""))]
        return [v for v in items if v]

    @staticmethod
    def _normalise_keyword_rules(value):
        """把关键词规则统一为 [{"keywords": [...], "reply": str, "match": "contains"|"exact"}]

        支持三种写法：
        - 规则列表：[{"keywords": ["教程", "怎么"], "reply": "…", "match": "contains"}]
        - 规则列表（简写）：[{"keyword": "教程", "content": "…"}]
        - 多行文本：每行「关键词1;关键词2 => 回复内容」，行首加 = 表示整条评论精确匹配，
          以 # 开头的行视为注释。
        """
        if isinstance(value, str):
            items = list(value.splitlines())
        elif isinstance(value, (list, tuple)):
            items = list(value)
        else:
            items = []

        rules = []
        for item in items:
            if isinstance(item, dict):
                keywords = Plugin._keyword_list(
                    item.get("keywords") or item.get("keyword"))
                reply = str(item.get("reply") or item.get("content") or "").strip()
                match = str(item.get("match") or "contains").strip().lower()
                if match not in ("contains", "exact"):
                    match = "contains"
            else:
                line = str(item or "").strip()
                if not line or line.startswith("#"):
                    continue
                left, right = None, None
                for sep in ("=>", "->", "|"):
                    if sep in line:
                        left, right = line.split(sep, 1)
                        break
                if left is None:
                    continue
                left = left.strip()
                match = "contains"
                if left.startswith("="):
                    match = "exact"
                    left = left.lstrip("=").strip()
                keywords = Plugin._keyword_list(left)
                reply = right.strip()

            keywords = [str(kw).strip()[:40] for kw in keywords if str(kw).strip()][:20]
            reply = reply[:500]
            if keywords and reply:
                rules.append({"keywords": keywords, "reply": reply, "match": match})
            if len(rules) >= 100:
                break
        return rules

    @staticmethod
    def _looks_local(base_url):
        base = str(base_url or "")
        return any(host in base for host in ("127.0.0.1", "localhost", "0.0.0.0", "192.168.", "10."))

    def _comment_cfg(self):
        merged = json.loads(json.dumps(DEFAULT_CONFIG["comment"], ensure_ascii=False))
        saved = self.config.get("comment")
        if isinstance(saved, dict):
            merged.update(saved)
        merged["keyword_rules"] = self._normalise_keyword_rules(
            merged.get("keyword_rules"))
        return merged

    def _llm_cfg(self):
        merged = json.loads(json.dumps(DEFAULT_CONFIG["llm"], ensure_ascii=False))
        saved = self.config.get("llm")
        if isinstance(saved, dict):
            merged.update(saved)

        # 兼容：没单独填 Key 时复用「AI 私信自动回复」插件的接口配置
        fallback = self._ai_plugin_llm()
        for field in ("base_url", "api_key", "model", "timeout"):
            if not str(merged.get(field) or "").strip() and fallback.get(field):
                merged[field] = fallback[field]
        merged["max_reply_chars"] = max(
            10, min(1000, self._to_int(merged.get("max_reply_chars"), 150)))
        return merged

    def _ai_plugin_llm(self):
        """读取 AI 私信插件的 llm 配置，作为未填写时的兜底（60 秒缓存）"""
        now = time.time()
        cached_at, cached = self._ai_fallback_cache
        if cached and now - cached_at < 60:
            return cached
        result = {}
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, "bilibot_plugins_ai_autoreply", "config.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                llm = data.get("llm") if isinstance(data, dict) else None
                if isinstance(llm, dict):
                    result = llm
        except Exception as e:
            self.logger.debug("读取 AI 私信插件配置失败: %s" % e)
        self._ai_fallback_cache = (now, result)
        return result

    # ---------- 评论区配置解析 ----------

    def _normalise_videos(self, raw):
        if isinstance(raw, str):
            raw = [line.strip() for line in raw.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        if not isinstance(raw, (list, tuple)):
            return []
        result = []
        seen = set()
        for item in raw:
            video = self._parse_video_item(item)
            if not video:
                continue
            key = "%s:%s" % (video["type"], video["oid"])
            if key in seen:
                continue
            seen.add(key)
            result.append(video)
            if len(result) >= MAX_VIDEOS:
                break
        return result

    def _parse_video_item(self, item):
        vtype = 1
        oid = ""
        title = ""
        account = ""

        if isinstance(item, dict):
            vtype = self._to_int(item.get("type"), 1)
            oid = str(item.get("oid") or item.get("id") or item.get("bvid")
                      or item.get("aid") or "").strip()
            title = str(item.get("title") or "").strip()
            account = str(item.get("account") or "").strip()
        else:
            text = str(item or "").strip()
            if not text:
                return None
            parts = [part.strip() for part in text.split("|")] if "|" in text else [text]
            # 兼容: 1|oid|标题|账号  或  oid|标题|账号
            if len(parts) >= 2 and re.fullmatch(r"\d+", parts[0] or ""):
                vtype = self._to_int(parts[0], 1)
                oid = parts[1]
                title = parts[2] if len(parts) > 2 else ""
                account = parts[3] if len(parts) > 3 else ""
            else:
                oid = parts[0]
                title = parts[1] if len(parts) > 1 else ""
                account = parts[2] if len(parts) > 2 else ""

        oid = str(oid or "").strip()
        if not oid:
            return None

        # URL / 简写解析
        bv_match = re.search(r"(BV[0-9A-Za-z]{10})", oid)
        if bv_match:
            oid = bv_match.group(1)
            vtype = 1
        elif re.search(r"bilibili\.com/read/cv(\d+)", oid, re.I):
            oid = re.search(r"bilibili\.com/read/cv(\d+)", oid, re.I).group(1)
            vtype = 12
        elif re.search(r"t\.bilibili\.com/(\d+)", oid, re.I):
            oid = re.search(r"t\.bilibili\.com/(\d+)", oid, re.I).group(1)
            vtype = 17
        elif re.search(r"bilibili\.com/video/av(\d+)", oid, re.I):
            oid = re.search(r"bilibili\.com/video/av(\d+)", oid, re.I).group(1)
            vtype = 1
        else:
            lower = oid.lower()
            if lower.startswith("cv"):
                vtype = 12
                oid = oid[2:]
            elif lower.startswith("av"):
                vtype = 1
                oid = oid[2:]
            elif lower.startswith("bv"):
                vtype = 1

        oid = str(oid).strip().strip("/")
        if not oid:
            return None
        if vtype not in (1, 12, 17):
            vtype = 1
        return {
            "type": vtype,
            "oid": oid,
            "title": title[:120],
            "account": account[:60],
        }

    @staticmethod
    def _video_key(video):
        return "%s:%s" % (video.get("type") or 1, video.get("oid") or "")

    # ================= 大模型 =================

    def _chat(self, messages, override=None, temperature=None, max_tokens=None):
        cfg = self._llm_cfg()
        if isinstance(override, dict):
            for key, value in override.items():
                if key == "api_key" and not str(value or "").strip():
                    continue  # 面板留空表示沿用已保存的 Key
                if value not in (None, ""):
                    cfg[key] = value

        base = str(cfg.get("base_url") or "").strip().rstrip("/")
        model = str(cfg.get("model") or "").strip()
        key = str(cfg.get("api_key") or "").strip()
        if not base or not model:
            raise LLMError("尚未配置大模型接口（base_url / model）")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"

        temp = self._to_float(temperature if temperature is not None else cfg.get("temperature"), 0.7)
        limit = self._to_int(max_tokens if max_tokens is not None else cfg.get("max_tokens"), 300)
        timeout = max(5, self._to_int(cfg.get("timeout"), 45))

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        payload = {
            "model": model,
            "messages": messages,
            "temperature": max(0.0, min(2.0, temp)),
            "max_tokens": max(16, min(8192, limit)),
            "stream": False,
        }

        started = time.time()
        try:
            resp = self.http.session.post(url, json=payload, headers=headers, timeout=timeout)
        except Exception as e:
            raise LLMError("无法连接大模型接口: %s" % e)
        if resp.status_code >= 400:
            raise LLMError("大模型接口返回 HTTP %s: %s"
                           % (resp.status_code, (resp.text or "")[:300]))
        try:
            data = resp.json()
        except ValueError:
            raise LLMError("大模型接口返回非 JSON（请确认 base_url 指向 OpenAI 兼容接口）")

        choices = data.get("choices") or []
        if not choices:
            error = data.get("error")
            if isinstance(error, dict):
                error = error.get("message")
            raise LLMError("大模型未返回内容" + (": %s" % error if error else ""))
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content
                              if isinstance(part, dict))
        content = str(content or "").strip()
        if not content:
            raise LLMError("大模型返回内容为空")

        self._stats["ai_calls"] += 1
        return {
            "text": content,
            "model": data.get("model") or model,
            "usage": data.get("usage") or {},
            "latency_ms": int((time.time() - started) * 1000),
        }

    def _clean_reply(self, text, max_chars=150):
        text = re.sub(r"^(?:回复|答复|回答|评论)\s*[:：]\s*", "", str(text or "").strip())
        text = text.strip("\"“”'‘’`").strip()
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return text

    # ================= 关键词规则 =================

    def _match_keyword_rule(self, content, cfg):
        """按配置顺序返回第一条命中的关键词规则，没有命中返回 None"""
        text = str(content or "").strip()
        if not text:
            return None
        lower = text.lower()
        rules = cfg.get("keyword_rules")
        if not isinstance(rules, list):
            rules = self._normalise_keyword_rules(rules)
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            for word in rule.get("keywords") or []:
                word = str(word or "").strip().lower()
                if not word:
                    continue
                if rule.get("match") == "exact":
                    if lower == word:
                        return rule
                elif word in lower:
                    return rule
        return None

    def _render_rule_reply(self, rule, job):
        """替换回复里的占位符：{nick} 评论者昵称、{title} 评论区标题"""
        text = str((rule or {}).get("reply") or "")
        values = {
            "nick": str(job.get("uname") or ""),
            "uname": str(job.get("uname") or ""),
            "user": str(job.get("uname") or ""),
            "title": str(job.get("title") or ""),
        }

        def replace(match):
            key = match.group(1).strip().lower()
            return values.get(key, match.group(0))

        text = re.sub(r"\{(\w+)\}", replace, text)
        return self._clean_reply(text, 500)

    # ================= 账号 / 请求 =================

    def _bots(self, cfg):
        bots = list(self.get_bot_accounts() or [])
        accounts = self._keyword_list(cfg.get("accounts"))
        if accounts:
            bots = [bot for bot in bots
                    if getattr(bot, "account_name", "") in accounts]
        return bots

    def _pick_bot(self, cfg, preferred=None):
        bots = self._bots(cfg)
        if not bots:
            return None
        if preferred:
            for bot in bots:
                if getattr(bot, "account_name", "") == preferred:
                    return bot
        return bots[0]

    def _find_bot(self, account_name):
        bots = list(self.get_bot_accounts() or [])
        for bot in bots:
            if getattr(bot, "account_name", None) == account_name:
                return bot
        return bots[0] if bots else None

    def _request_headers(self, bot, referer=None):
        headers = {}
        bot_headers = getattr(bot, "headers", None) or {}
        if isinstance(bot_headers, dict):
            headers.update(bot_headers)
        cookie = headers.get("Cookie") or ""
        if not cookie:
            parts = []
            for key, attr in (("SESSDATA", "sessdata"), ("bili_jct", "bili_jct"),
                              ("DedeUserID", "self_uid")):
                value = getattr(bot, attr, "")
                if value:
                    parts.append("%s=%s" % (key, value))
            cookie = "; ".join(parts)
        headers["Cookie"] = cookie
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")
        headers.setdefault("Accept", "application/json, text/plain, */*")
        headers.setdefault("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
        if referer:
            headers["Referer"] = referer
            headers["Origin"] = "https://www.bilibili.com"
        return headers

    @staticmethod
    def _video_referer(video):
        vtype = video.get("type") or 1
        oid = str(video.get("oid") or "")
        if vtype == 12:
            return "https://www.bilibili.com/read/cv%s" % oid
        if vtype == 17:
            return "https://t.bilibili.com/%s" % oid
        bvid = video.get("bvid")
        if bvid:
            return "https://www.bilibili.com/video/%s" % bvid
        return "https://www.bilibili.com/video/av%s" % oid

    def _get_json(self, url, params, bot, referer=None, timeout=20):
        try:
            resp = self.http.session.get(
                url, params=params, headers=self._request_headers(bot, referer), timeout=timeout)
        except Exception as e:
            raise CommentError("无法连接 B 站接口: %s" % e)
        if resp.status_code != 200:
            raise CommentError("B 站接口返回 HTTP %s" % resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise CommentError("B 站接口返回非 JSON（可能触发风控）")

    def _resolve_video(self, bot, video):
        """把 BV 转成 aid，并尽量补全标题（按进程缓存）"""
        video = dict(video)
        vtype = self._to_int(video.get("type"), 1)
        oid = str(video.get("oid") or "").strip()
        cache_key = "%s:%s" % (vtype, oid)
        cached = self._video_cache.get(cache_key)
        if cached:
            result = dict(cached)
            if video.get("title"):
                result["title"] = video["title"]
            if video.get("account"):
                result["account"] = video["account"]
            return result

        if vtype == 1:
            needs_view = (oid.upper().startswith("BV")
                          or not oid.isdigit()
                          or not video.get("title"))
            if needs_view:
                params = {"bvid": oid} if oid.upper().startswith("BV") else {"aid": oid}
                data = self._get_json(VIEW_URL, params, bot, self._video_referer(video))
                if self._to_int(data.get("code"), -1) == 0 and isinstance(data.get("data"), dict):
                    info = data["data"]
                    video["oid"] = str(info.get("aid") or oid)
                    video["bvid"] = info.get("bvid") or ""
                    if not video.get("title"):
                        video["title"] = str(info.get("title") or "").strip()
                elif not oid.isdigit():
                    raise CommentError("无法解析视频 %s: %s" % (
                        oid, data.get("message") or "接口返回错误"))
            if not video.get("title"):
                video["title"] = "视频 av%s" % video.get("oid")
        elif vtype == 12:
            if not video.get("title"):
                video["title"] = "专栏 cv%s" % oid
        elif vtype == 17:
            if not video.get("title"):
                video["title"] = "动态 %s" % oid

        self._video_cache[cache_key] = dict(video)
        return video

    # ================= 扫描 =================

    def _start_threads(self):
        if not (self._worker and self._worker.is_alive()):
            self._stop = threading.Event()
            self._worker = threading.Thread(
                target=self._worker_loop, daemon=True,
                name="comment-autoreply-worker")
            self._worker.start()
        if not (self._poller and self._poller.is_alive()):
            self._poller = threading.Thread(
                target=self._poll_loop, daemon=True,
                name="comment-autoreply-poller")
            self._poller.start()

    def _poll_loop(self):
        while not self._stop.is_set():
            cfg = self._comment_cfg()
            if not cfg.get("enabled"):
                self._stop.wait(10)
                continue
            interval = max(30, min(3600, self._to_int(
                cfg.get("poll_interval_seconds"), 120)))
            now = time.time()
            if now - self._last_scan_tried >= interval:
                self._last_scan_tried = now
                try:
                    self._scan_once()
                except Exception as e:
                    self._last_error = str(e)
                    self.logger.error("评论区扫描异常: %s" % e)
            self._stop.wait(min(5, max(1, interval)))

    def _scan_once(self, force=False):
        if not self._scan_lock.acquire(blocking=False):
            self._log_scan("info", "已有评论扫描正在进行，跳过本次")
            return False
        started = time.time()
        try:
            cfg = self._comment_cfg()
            if not cfg.get("enabled") and not force:
                return False
            videos = self._normalise_videos(cfg.get("videos"))
            feed_enabled = self._bool(cfg.get("message_feed"))
            self._last_scan_at = started
            if not videos and not feed_enabled:
                if force:
                    self._last_error = "尚未配置任何评论区，也未开启评论消息扫描"
                    self._log_scan("warning", self._last_error)
                return False
            self._log_scan(
                "info", "开始扫描（%s）：评论区 %s 个，评论消息=%s，dry_run=%s" % (
                    "手动" if force else "定时", len(videos),
                    "开" if feed_enabled else "关",
                    "开" if self._bool(cfg.get("dry_run")) else "关"))
            if feed_enabled:
                try:
                    self._scan_message_feed(cfg)
                except CommentError as e:
                    self._last_error = str(e)
                    self._log_scan("error", "扫描评论消息失败: %s" % e)
                except Exception as e:
                    self._last_error = str(e)
                    self._log_scan("error", "扫描评论消息异常: %s" % e)
            for video in videos:
                if self._stop.is_set():
                    break
                try:
                    self._scan_video(cfg, video)
                except CommentError as e:
                    self._last_error = str(e)
                    self._log_scan("error", "扫描评论区 %s:%s 失败: %s" % (
                        video.get("type"), video.get("oid"), e))
                except Exception as e:
                    self._last_error = str(e)
                    self._log_scan("error", "扫描评论区 %s:%s 异常: %s" % (
                        video.get("type"), video.get("oid"), e))
                self._stop.wait(1)
            self._last_scan_at = time.time()
            self._last_scan_duration = int((self._last_scan_at - started) * 1000)
            self._log_scan(
                "info", "扫描结束：用时 %ss，扫描 %s 条，入队 %s 条，累计今日回复 %s 条" % (
                    round(self._last_scan_duration / 1000.0, 1),
                    self._stats["scanned"], self._stats["queued"],
                    self._replies_today()))
            return True
        finally:
            self._scan_lock.release()

    def _scan_video(self, cfg, video):
        bot = self._pick_bot(cfg, video.get("account"))
        if bot is None:
            raise CommentError("没有可用账号（请检查账号名称或机器人是否启动）")
        video = self._resolve_video(bot, video)
        vkey = self._video_key(video)
        ps = 20
        max_pages = max(1, min(5, self._to_int(cfg.get("max_pages_per_scan"), 2)))

        comments = []
        local_seen = set()
        sort_mode = 0  # 0=按时间，1=按点赞
        for pn in range(1, max_pages + 1):
            data = self._fetch_comments(bot, video, pn, ps, sort=sort_mode)
            replies = data.get("replies") or []
            if (pn == 1 and sort_mode == 0 and not replies):
                # B 站对匿名/无 Cookie 请求的 sort=0 常返回空列表（code=0 但无数据），
                # 回退到按点赞排序，避免整轮扫描误判为“没有评论”。
                alt = self._fetch_comments(bot, video, pn, ps, sort=1)
                alt_replies = alt.get("replies") or []
                if isinstance(alt_replies, list) and alt_replies:
                    sort_mode = 1
                    replies = alt_replies
                    self.logger.warning(
                        "评论区 %s：按时间排序返回空，已回退到按点赞排序" % (
                            video.get("title") or self._video_key(video)))
            if not isinstance(replies, list):
                break
            for raw in replies:
                row = self._comment_row(raw)
                if not row or row["rpid"] in local_seen:
                    continue
                local_seen.add(row["rpid"])
                comments.append(row)
            # 按时间排序时，本页出现已处理评论即可认为翻到了上次扫描的位置；
            # 回退到按点赞排序后顺序与时间无关，不能用该规则提前停止。
            if sort_mode == 0 and any(self._seen(vkey, row["rpid"]) for row in comments):
                break
            if len(replies) < ps:
                break
            if pn < max_pages:
                self._stop.wait(1)

        comments.sort(key=lambda row: (row.get("ctime") or 0, row.get("rpid") or ""))
        self._log_scan("info", "评论区 %s：本轮抓取 %s 条评论" % (
            video.get("title") or vkey, len(comments)))

        state = self.database.fetch_one(
            "SELECT baseline_at FROM comment_scan_state WHERE key = ?", (vkey,))
        now = time.time()
        if state is None and not self._bool(cfg.get("reply_on_first_scan")):
            for row in comments:
                self._mark_seen(vkey, row["rpid"])
            self.database.execute(
                "INSERT OR REPLACE INTO comment_scan_state "
                "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
                (vkey, now, now))
            self._stats["baseline"] += len(comments)
            self.logger.info(
                "评论区 %s 首次扫描，已记录基线 %s 条评论（不回复历史评论）" % (
                    video.get("title") or vkey, len(comments)))
            return

        if state is None:
            self.database.execute(
                "INSERT OR REPLACE INTO comment_scan_state "
                "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
                (vkey, 0, now))

        budget = max(0, self._to_int(cfg.get("max_replies_per_scan"), 20))
        queued = 0
        for row in comments:
            if self._seen(vkey, row["rpid"]):
                continue
            # 无论是否回复都标记为已处理，避免下一轮反复判断
            self._mark_seen(vkey, row["rpid"])
            self._stats["scanned"] += 1

            reason = self._skip_reason(row, cfg, bot)
            if not reason and budget <= 0:
                reason = "达到单次扫描上限"
            if reason:
                self._stats["skipped"] += 1
                self._log_scan("info", "跳过评论区评论 %s（%s）: %s" % (
                    row["rpid"], row.get("uname") or row.get("mid") or "未知用户", reason))
                continue

            job = {
                "account_name": getattr(bot, "account_name", ""),
                "type": video.get("type") or 1,
                "oid": str(video.get("oid") or ""),
                "bvid": video.get("bvid") or "",
                "title": video.get("title") or "",
                "rpid": row["rpid"],
                "mid": row["mid"],
                "uname": row["uname"],
                "content": row["content"],
                "ctime": row["ctime"],
            }
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                self._stats["skipped"] += 1
                self._log_scan("warning", "评论回复队列已满，丢弃评论 %s" % row["rpid"])
                break
            self._stats["queued"] += 1
            self._touch_cooldown(row["mid"])
            budget -= 1
            queued += 1
            self._log_scan("info", "评论入队 %s（%s）: %s" % (
                row["rpid"], row.get("uname") or row.get("mid") or "未知用户",
                str(row.get("content") or "")[:60]))

        self.database.execute(
            "INSERT OR REPLACE INTO comment_scan_state "
            "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
            (vkey, state[0] if state else 0, now))
        if queued:
            self._log_scan("info", "评论区 %s：发现 %s 条待回复评论" % (
                video.get("title") or vkey, queued))

    def _fetch_comments(self, bot, video, pn, ps, sort=0):
        vtype = self._to_int(video.get("type"), 1)
        oid = str(video.get("oid") or "")
        params = {
            "type": vtype,
            "oid": oid,
            "sort": sort,    # 0=按时间，1=按点赞
            "nohot": 1,      # 不返回热评
            "ps": ps,
            "pn": pn,
        }
        data = self._get_json(COMMENT_URL, params, bot, self._video_referer(video))
        code = self._to_int(data.get("code"), -1)
        if code != 0:
            raise CommentError("评论列表接口错误 %s: %s" % (
                code, data.get("message") or "未知错误"))
        payload = data.get("data")
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _comment_row(raw):
        if not isinstance(raw, dict):
            return None
        rpid = str(raw.get("rpid") or raw.get("rpid_str") or "").strip()
        if not rpid:
            return None
        content = raw.get("content")
        message = ""
        if isinstance(content, dict):
            message = str(content.get("message") or "").strip()
        member = raw.get("member") if isinstance(raw.get("member"), dict) else {}
        return {
            "rpid": rpid,
            "mid": str(raw.get("mid") or member.get("mid") or ""),
            "uname": str(member.get("uname") or "").strip(),
            "content": message,
            "ctime": Plugin._to_int(raw.get("ctime"), 0),
            "state": raw.get("state", 0),
            "root": Plugin._to_int(raw.get("root"), 0),
        }

    # ---------- 评论消息（回复我的 / @我的） ----------

    def _scan_message_feed(self, cfg):
        """扫描消息中心的「回复我的」，不依赖 videos 配置"""
        bots = self._bots(cfg)
        if not bots:
            raise CommentError("没有可用账号（请检查账号名称或机器人是否启动）")
        scanned = set()
        for bot in bots:
            if self._stop.is_set():
                break
            uid = str(getattr(bot, "self_uid", "") or getattr(bot, "account_name", ""))
            if uid in scanned:
                continue
            scanned.add(uid)
            try:
                self._scan_message_feed_bot(cfg, bot)
            except CommentError as e:
                self._last_error = str(e)
                self.logger.error("扫描账号 %s 的评论消息失败: %s" % (
                    getattr(bot, "account_name", uid), e))
            except Exception as e:
                self._last_error = str(e)
                self.logger.error("扫描账号 %s 的评论消息异常: %s" % (
                    getattr(bot, "account_name", uid), e))
            self._stop.wait(1)

    def _fetch_msgfeed(self, bot, url=MSG_REPLY_URL, label="回复我的"):
        """请求消息接口，返回完整 JSON（含 code/message/data），失败抛 CommentError"""
        params = {
            "build": 0,
            "mobi_app": "web",
            "platform": "web",
            "web_location": "333.1387",
        }
        data = self._get_json(url, params, bot, "https://message.bilibili.com/")
        code = self._to_int(data.get("code"), -1)
        if code != 0:
            raise CommentError("%s消息接口错误 %s: %s" % (
                label, code, data.get("message") or "未知错误"))
        if not isinstance(data.get("data"), dict):
            data = dict(data)
            data["data"] = {}
        return data

    def _fetch_msgfeed_unread(self, bot):
        """未读数（best-effort，仅用于日志与调试，不影响主流程）"""
        try:
            data = self._get_json(
                MSG_UNREAD_URL,
                {"build": 0, "mobi_app": "web", "platform": "web"},
                bot, "https://message.bilibili.com/")
        except Exception as e:
            self.logger.debug("读取消息未读数失败: %s" % e)
            return {}
        payload = data.get("data")
        return payload if isinstance(payload, dict) else {}

    def _dump_msgfeed_debug(self, account, sections):
        """把消息接口原始返回写进本地文本文件，方便人工排查

        sections: [(标题, 请求信息 dict, 接口原始 JSON dict)]
        写入 MSGFEED_DEBUG_PATH（默认 .tmp/msgfeed_debug.txt），追加模式，
        文件超过 MSGFEED_DEBUG_LIMIT 时自动重写，避免无限增长。
        """
        try:
            # __file__ = <项目>/plugins/<插件>/main.py，向上三层才是项目根目录
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            path = os.path.join(root, MSGFEED_DEBUG_PATH)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > MSGFEED_DEBUG_LIMIT:
                try:
                    os.remove(path)
                except OSError:
                    pass
            lines = ["", "=" * 78,
                     "时间: %s  账号: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), account)]
            for title, meta, payload in sections:
                lines.append("-" * 78)
                lines.append("[%s] %s" % (title, meta.get("url", "")))
                lines.append("参数: %s" % json.dumps(
                    meta.get("params") or {}, ensure_ascii=False))
                data = payload.get("data") if isinstance(payload, dict) else None
                counts = ""
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    counts = "  items=%s" % len(data["items"])
                lines.append("code=%s message=%s%s" % (
                    payload.get("code") if isinstance(payload, dict) else "?",
                    payload.get("message") if isinstance(payload, dict) else "?",
                    counts))
                lines.append("原始返回:")
                lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return path
        except Exception as e:
            self.logger.warning("写入消息调试文件失败: %s" % e)
            return ""

    def _scan_message_feed_bot(self, cfg, bot):
        account = getattr(bot, "account_name", "") or str(getattr(bot, "self_uid", ""))
        raw_items = []
        sections = []
        failures = []
        # 1) 回复我的  2) @我的（两个接口返回结构一致，但通知内容不重合）
        for title, url, label in (("回复我的", MSG_REPLY_URL, "回复我的"),
                                  ("@我的", MSG_AT_URL, "@我的")):
            try:
                payload = self._fetch_msgfeed(bot, url, label)
            except CommentError as e:
                failures.append(str(e))
                sections.append((title, {"url": url, "params": {
                    "build": 0, "mobi_app": "web", "platform": "web",
                    "web_location": "333.1387"}}, {"code": "ERROR", "message": str(e)}))
                self._log_scan("warning", "账号 %s：%s 接口失败: %s" % (account, label, e))
                continue
            items = (payload.get("data") or {}).get("items")
            items = items if isinstance(items, list) else []
            sections.append((title, {"url": url, "params": {
                "build": 0, "mobi_app": "web", "platform": "web",
                "web_location": "333.1387"}}, payload))
            raw_items.extend(items)
            self._log_scan("info", "账号 %s：%s 接口返回 %s 条通知" % (
                account, label, len(items)))

        unread = self._fetch_msgfeed_unread(bot)
        if unread:
            sections.append(("未读数", {
                "url": MSG_UNREAD_URL,
                "params": {"build": 0, "mobi_app": "web", "platform": "web"}},
                {"code": 0, "data": unread}))
            self._log_scan("info", "账号 %s：消息未读数 回复=%s @=%s" % (
                account, unread.get("reply"), unread.get("at")))

        dump_path = self._dump_msgfeed_debug(account, sections)
        if dump_path:
            self._log_scan("info", "消息接口原始返回已写入 %s（%s 条通知）" % (
                dump_path, len(raw_items)))

        if failures and not raw_items:
            raise CommentError("；".join(failures))
        if failures:
            self._log_scan("warning", "部分消息接口失败（已用其余接口继续）: %s" % (
                "；".join(failures)))

        # 同一通知可能同时出现在 @ 与回复里，按 rpid 去重
        dedup = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("id") or "")
            item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
            key = key or str(item.get("source_id") or "")
            if key and key in dedup:
                continue
            if key:
                dedup[key] = raw
            else:
                dedup["_%d" % len(dedup)] = raw
        raw_items = list(dedup.values())

        uid = str(getattr(bot, "self_uid", "") or getattr(bot, "account_name", ""))
        vkey = "msgfeed:%s" % uid
        rows = []
        for raw in raw_items:
            row = self._msgfeed_row(raw)
            if not row:
                extra = (raw.get("item") or {}) if isinstance(raw, dict) else {}
                self._log_scan("warning",
                               "评论消息解析失败（缺 rpid/内容/oid），已忽略: %s" % (
                                   str(extra.get("source_id") or raw.get("id") or "未知")[:40]))
                continue
            if row.get("type") == 1 and str(row.get("oid") or "").upper().startswith("BV"):
                try:
                    resolved = self._resolve_video(bot, {
                        "type": 1,
                        "oid": row["oid"],
                        "bvid": row["oid"],
                        "title": row.get("title") or "",
                    })
                except CommentError as e:
                    # 视频信息接口可能因为稿件不可见/审核中而失败，但通知里通常带有 aid
                    # （subject_id）。只要还能拿到 aid，就继续入队，避免漏掉 @我/回复我。
                    fallback = str(row.get("subject_id") or "").strip()
                    if fallback.upper().startswith("BV"):
                        try:
                            resolved = self._resolve_video(bot, {
                                "type": 1, "oid": fallback, "bvid": fallback,
                                "title": row.get("title") or "",
                            })
                        except CommentError:
                            resolved = None
                        if resolved:
                            row["oid"] = str(resolved.get("oid") or fallback)
                            row["bvid"] = resolved.get("bvid") or fallback
                            row["title"] = row.get("title") or resolved.get("title") or ""
                            self._log_scan(
                                "warning",
                                "评论消息中的视频 %s 解析失败，改用通知里的 subject_id=%s "
                                "重新解析成功（rpid=%s）" % (
                                    row.get("oid"), fallback, row.get("rpid")))
                            fallback = ""
                    if fallback.isdigit():
                        self._log_scan(
                            "warning",
                            "评论消息中的视频 %s 解析失败，改用通知里的 subject_id=%s "
                            "作为 aid 继续处理（rpid=%s）：%s" % (
                                row.get("oid"), fallback, row.get("rpid"), e))
                        row["oid"] = fallback
                        row["bvid"] = row.get("bvid") or ""
                        row["title"] = row.get("title") or ("视频 av%s" % fallback)
                    elif fallback:
                        self._log_scan(
                            "warning",
                            "评论消息中的视频 %s 解析失败，且通知里的 subject_id=%s "
                            "也无法使用，已跳过 rpid=%s：%s" % (
                                row.get("oid"), fallback, row.get("rpid"), e))
                        continue
                    else:
                        self._log_scan(
                            "warning",
                            "评论消息中的视频 %s 解析失败，且通知里没有可用的 aid，"
                            "已跳过 rpid=%s：%s" % (
                                row.get("oid"), row.get("rpid"), e))
                        continue
                else:
                    row["oid"] = str(resolved.get("oid") or row["oid"])
                    row["bvid"] = resolved.get("bvid") or row.get("bvid") or ""
                    row["title"] = row.get("title") or resolved.get("title") or ""
            if self._seen_any(row["rpid"]):
                self._log_scan("info", "评论消息 %s 之前已处理过，跳过" % row["rpid"])
                continue
            self._log_scan("info", "收到评论消息 rpid=%s：%s 在「%s」%s: %s" % (
                row["rpid"], row.get("uname") or row.get("mid") or "未知用户",
                (row.get("title") or "")[:30],
                COMMENT_TYPE_NAMES.get(self._to_int(row.get("type"), 1), "视频"),
                str(row.get("content") or "")[:60]))
            rows.append(row)

        rows.sort(key=lambda row: (row.get("ctime") or 0, row.get("rpid") or ""))
        now = time.time()
        state = self.database.fetch_one(
            "SELECT baseline_at FROM comment_scan_state WHERE key = ?", (vkey,))
        if state is None and not self._bool(cfg.get("reply_on_first_scan")):
            for row in rows:
                self._mark_feed_seen(row, vkey)
            self.database.execute(
                "INSERT OR REPLACE INTO comment_scan_state "
                "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
                (vkey, now, now))
            self._stats["baseline"] += len(rows)
            self._log_scan("info",
                           "账号 %s 首次扫描评论消息，已记录基线 %s 条（不回复历史消息）" % (
                               getattr(bot, "account_name", uid), len(rows)))
            return

        if state is None:
            self.database.execute(
                "INSERT OR REPLACE INTO comment_scan_state "
                "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
                (vkey, 0, now))

        budget = max(0, self._to_int(cfg.get("max_replies_per_scan"), 20))
        queued = 0
        for row in rows:
            if self._seen_any(row["rpid"]):
                continue
            # 无论是否回复都标记为已处理，避免下一轮反复判断
            self._mark_feed_seen(row, vkey)
            self._stats["scanned"] += 1

            reason = self._skip_reason(row, cfg, bot)
            if not reason and budget <= 0:
                reason = "达到单次扫描上限"
            if reason:
                self._stats["skipped"] += 1
                self._log_scan("info", "跳过评论消息 %s（%s）: %s" % (
                    row["rpid"], row.get("uname") or row.get("mid") or "未知用户", reason))
                continue

            job = {
                "account_name": getattr(bot, "account_name", ""),
                "type": row.get("type") or 1,
                "oid": str(row.get("oid") or ""),
                "bvid": row.get("bvid") or "",
                "title": row.get("title") or "",
                "rpid": row["rpid"],
                "root_rpid": row.get("root_rpid") or row["rpid"],
                "parent_rpid": row.get("parent_rpid") or row["rpid"],
                "mid": row["mid"],
                "uname": row["uname"],
                "content": row["content"],
                "ctime": row["ctime"],
                "source": "message",
            }
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                self._stats["skipped"] += 1
                self._log_scan("warning", "评论回复队列已满，丢弃评论消息 %s" % row["rpid"])
                break
            self._stats["queued"] += 1
            self._touch_cooldown(row["mid"])
            budget -= 1
            queued += 1
            self._log_scan("info", "评论消息已入队 %s: %s" % (
                row["rpid"], str(row.get("content") or "")[:60]))

        self.database.execute(
            "INSERT OR REPLACE INTO comment_scan_state "
            "(key, baseline_at, last_scan_at) VALUES (?, ?, ?)",
            (vkey, state[0] if state else 0, now))
        if queued:
            self._log_scan("info", "账号 %s：从评论消息发现 %s 条待回复评论" % (
                getattr(bot, "account_name", uid), queued))

    @classmethod
    def _msgfeed_row(cls, raw):
        """把「回复我的」通知转换成与评论区一致的行结构"""
        if not isinstance(raw, dict):
            return None
        item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
        source_id = str(item.get("source_id") or "").strip()
        if not source_id.isdigit():
            return None
        content = str(item.get("source_content") or "").strip()
        if not content:
            return None

        user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
        vtype, oid, bvid, title = cls._msgfeed_target(item)
        if not oid:
            return None
        root_id = str(item.get("root_id") or "0").strip()
        root_rpid = source_id if root_id in ("", "0") else root_id
        return {
            "rpid": source_id,
            "mid": str(user.get("mid") or "").strip(),
            "uname": str(user.get("nickname") or "").strip(),
            "content": content,
            "ctime": cls._to_int(raw.get("reply_time") or raw.get("at_time"), 0),
            "state": 0,
            "root": 0,          # 消息可能来自楼中楼，交给 _send_reply 用 root/parent 处理
            "directed": True,   # 本身就是 @我 / 回复我，不受 only_mention 限制
            "type": vtype,
            "oid": oid,
            "bvid": bvid,
            "title": title,
            "root_rpid": root_rpid,
            "parent_rpid": source_id,
            "notice_id": str(raw.get("id") or "").strip(),
            # 视频通知里的 subject_id 通常是 aid：BV 解析失败时用它兜底
            "subject_id": str(item.get("subject_id") or "").strip(),
        }

    @classmethod
    def _msgfeed_target(cls, item):
        """从通知的 uri / business_id 推断评论类型与 oid"""
        uri = str(item.get("uri") or item.get("native_uri") or "")
        title = str(item.get("title") or "").strip()
        vtype = 0
        oid = ""
        bvid = ""

        match = re.search(r"bilibili\.com/video/(BV[0-9A-Za-z]{10})", uri)
        if not match:
            match = re.search(r"bilibili\.com/video/av(\d+)", uri, re.I)
        if match:
            vtype = 1
            oid = match.group(1)
            if oid.upper().startswith("BV"):
                bvid = oid
        else:
            match = re.search(r"bilibili\.com/read/cv(\d+)", uri, re.I)
            if match:
                vtype = 12
                oid = match.group(1)
            else:
                match = re.search(r"t\.bilibili\.com/(\d+)", uri, re.I)
                if not match:
                    match = re.search(r"bilibili\.com/opus/(\d+)", uri, re.I)
                if match:
                    vtype = 17
                    oid = match.group(1)

        if not oid:
            business_id = cls._to_int(item.get("business_id"), 0)
            oid = str(item.get("subject_id") or "").strip()
            vtype = {1: 1, 12: 12, 11: 17, 17: 17}.get(business_id, 0)
            if not vtype:
                business = str(item.get("business") or "")
                if "专栏" in business or "文章" in business:
                    vtype = 12
                elif "动态" in business:
                    vtype = 17
                elif "视频" in business:
                    vtype = 1
            if not vtype:
                vtype = 1

        oid = str(oid).strip()
        if not oid:
            return 0, "", "", title
        if vtype not in (1, 12, 17):
            vtype = 1
        if not title:
            if vtype == 1:
                title = "视频 av%s" % oid
            elif vtype == 12:
                title = "专栏 cv%s" % oid
            else:
                title = "动态 %s" % oid
        return vtype, oid, bvid, title[:120]

    def _mark_feed_seen(self, row, vkey):
        rpid = str(row.get("rpid") or "")
        if not rpid:
            return
        self._mark_seen(vkey, rpid)
        vtype = self._to_int(row.get("type"), 1)
        oid = str(row.get("oid") or "")
        if oid:
            self._mark_seen("%s:%s" % (vtype, oid), rpid)

    def _seen_any(self, rpid):
        """rpid 全局唯一：检查该评论是否已被任意来源处理过"""
        rpid = str(rpid or "").strip()
        if not rpid.isdigit():
            return False
        row = self.database.fetch_one(
            "SELECT key FROM comment_seen WHERE key LIKE ? LIMIT 1",
            ("%:" + rpid,))
        return bool(row)

    def _skip_reason(self, row, cfg, bot):
        content = str(row.get("content") or "").strip()
        if not content:
            return "空评论"
        directed = bool(row.get("directed"))
        if not directed and str(row.get("root") or "0") not in ("0", ""):
            return "楼中楼评论（只回复一级评论）"
        own_uid = str(getattr(bot, "self_uid", "") or "")
        if own_uid and str(row.get("mid") or "") == own_uid:
            return "自己发的评论"

        ignore_uids = set(self._keyword_list(cfg.get("ignore_uids")))
        if ignore_uids and str(row.get("mid") or "") in ignore_uids:
            return "用户在忽略名单"

        if row.get("state") not in (None, 0, "0"):
            return "评论状态异常"

        max_age = self._to_int(cfg.get("max_comment_age_seconds"), 0)
        if max_age > 0 and row.get("ctime"):
            if time.time() - int(row["ctime"]) > max_age:
                return "评论过旧"

        lower = content.lower()
        ignores = self._keyword_list(cfg.get("ignore_keywords"))
        if any(word.lower() in lower for word in ignores):
            return "命中忽略关键词"

        triggers = self._keyword_list(cfg.get("trigger_keywords"))
        hit_trigger = any(word.lower() in lower for word in triggers) if triggers else False
        # 评论消息里的 @我 / 回复我 本身就是针对本账号的，不受触发关键词限制
        if triggers and not hit_trigger and not directed:
            return "未命中触发关键词"

        if self._bool(cfg.get("only_mention")) and not hit_trigger and not directed:
            if not re.search(r"@[^\s@]{1,30}", content):
                return "未 @UP 且未命中关键词"

        if self._bool(cfg.get("keyword_only")) and self._match_keyword_rule(content, cfg) is None:
            return "未命中关键词规则（仅关键词模式）"

        if not self._check_cooldown(row.get("mid"), cfg):
            return "用户冷却中"
        if not self._under_daily_limit(cfg):
            return "达到每日上限"
        return ""

    # ---------- 去重 / 限流 ----------

    @staticmethod
    def _seen_key(vkey, rpid):
        return "%s:%s" % (vkey, rpid)

    def _seen(self, vkey, rpid):
        row = self.database.fetch_one(
            "SELECT key FROM comment_seen WHERE key = ?",
            (self._seen_key(vkey, rpid),))
        return bool(row)

    def _mark_seen(self, vkey, rpid):
        self.database.execute(
            "INSERT OR IGNORE INTO comment_seen (key, created_at) VALUES (?, ?)",
            (self._seen_key(vkey, rpid), time.time()))

    def _prune_seen(self):
        try:
            self.database.execute(
                "DELETE FROM comment_seen WHERE created_at < ?",
                (time.time() - SEEN_RETENTION_SECONDS,))
            self.database.execute(
                "DELETE FROM comment_reply_log WHERE id NOT IN "
                "(SELECT id FROM comment_reply_log ORDER BY id DESC LIMIT ?)",
                (MAX_HISTORY_ROWS,))
        except Exception as e:
            self.logger.error("清理评论插件数据失败: %s" % e)

    # ---------- 扫描日志 ----------

    def _log_scan(self, level, message):
        """记录一条扫描日志：同时写入插件日志文件与面板内存缓冲

        面板「扫描日志」只展示最近 500 条，插件日志仍然完整落盘。
        """
        message = str(message or "").strip()
        if not message:
            return
        text = time.strftime("%H:%M:%S") + " " + message
        with self._scan_log_lock:
            self._scan_logs.append({
                "time": text,
                "level": level,
                "message": message,
            })
        log = {"info": self.logger.info, "warning": self.logger.warning,
               "error": self.logger.error}.get(level, self.logger.info)
        log(message)

    def api_logs(self, data):
        limit = max(1, min(500, self._to_int(self._p(data, "limit"), 200)))
        with self._scan_log_lock:
            items = list(self._scan_logs)[-limit:]
        return {"success": True, "items": items}

    def api_logs_clear(self, data):
        with self._scan_log_lock:
            self._scan_logs.clear()
        return {"success": True, "message": "扫描日志已清空"}

    def _cooldown_left(self, mid, cfg):
        if not mid:
            return 0
        seconds = max(0, self._to_int(cfg.get("cooldown_seconds"), 60))
        if seconds <= 0:
            return 0
        with self._lock:
            last = self._cooldown.get(str(mid), 0)
        if not last:
            row = self.database.fetch_one(
                "SELECT MAX(created_at) FROM comment_reply_log "
                "WHERE mid = ? AND ok = 1 AND note = 'sent'", (str(mid),))
            last = float(row[0]) if row and row[0] else 0
        return max(0, int(seconds - (time.time() - last)))

    def _check_cooldown(self, mid, cfg):
        return self._cooldown_left(mid, cfg) <= 0

    def _touch_cooldown(self, mid):
        if not mid:
            return
        with self._lock:
            self._cooldown[str(mid)] = time.time()
        if len(self._cooldown) > 5000:
            with self._lock:
                self._cooldown.clear()

    @staticmethod
    def _day_start():
        now = time.localtime()
        return time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                            0, 0, 0, 0, 0, -1))

    def _replies_today(self):
        row = self.database.fetch_one(
            "SELECT COUNT(*) FROM comment_reply_log "
            "WHERE ok = 1 AND (note = 'sent' OR note = 'keyword' OR note LIKE 'fallback_%') "
            "AND created_at >= ?",
            (self._day_start(),))
        return int(row[0]) if row else 0

    def _under_daily_limit(self, cfg):
        limit = self._to_int(cfg.get("max_replies_per_day"), 100)
        if limit <= 0:
            return True
        return self._replies_today() + self._queue.qsize() < limit

    # ================= 回复工作线程 =================

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            if job is None:
                break
            self._log_scan("info", "开始处理评论 %s（来源：%s，目标：%s:%s）" % (
                job.get("rpid"), "评论消息" if job.get("source") == "message" else "评论区",
                job.get("type"), job.get("oid")))
            try:
                self._process_job(job)
            except Exception as e:
                self._stats["failed"] += 1
                self._last_error = str(e)
                self.logger.error("评论回复任务异常: %s" % e)
                self._log_scan("error", "评论回复任务 %s 异常: %s" % (
                    job.get("rpid"), str(e)[:200]))

    def _process_rule_job(self, job, cfg, rule):
        """命中关键词规则：直接使用固定回复内容，不调用大模型"""
        started = time.time()
        text = self._render_rule_reply(rule, job)
        latency = int((time.time() - started) * 1000)
        if not text:
            self._stats["failed"] += 1
            self._last_error = "关键词规则回复内容为空"
            self._log_reply(job, "", "keyword", latency, 0, "empty_keyword_reply")
            self._log_scan("warning", "关键词规则回复内容为空，跳过评论 %s" % job.get("rpid"))
            return

        if self._bool(cfg.get("dry_run")):
            self._stats["skipped"] += 1
            self._stats["keyword_replies"] += 1
            self._log_reply(job, text, "keyword", latency, 1, "keyword_dry_run")
            self._log_scan("info", "[dry-run] 关键词规则将回复评论 %s: %s" % (
                job.get("rpid"), text[:80]))
            return

        ok, note = self._send_reply(job, text)
        if ok:
            self._stats["keyword_replies"] += 1
            self._stats["replies_sent"] += 1
            self._log_reply(job, text, "keyword", latency, 1, "keyword")
            self._cooldown[str(job.get("mid") or "")] = time.time()
            self._log_scan("info", "关键词规则已回复评论 %s: %s" % (
                job.get("rpid"), text[:80]))
        else:
            self._stats["failed"] += 1
            self._log_reply(job, text, "keyword", latency, 0, note)
            self._log_scan("error", "关键词规则回复评论 %s 失败: %s" % (
                job.get("rpid"), note))

    def _process_job(self, job):
        cfg = self._comment_cfg()
        rule = self._match_keyword_rule(job.get("content"), cfg)
        if rule:
            self._process_rule_job(job, cfg, rule)
            return

        llm = self._llm_cfg()
        max_chars = self._to_int(llm.get("max_reply_chars"), 150)
        started = time.time()

        system_prompt = str(llm.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
        user_prompt = (
            "评论区标题：%s\n"
            "评论者：%s\n"
            "评论内容：%s\n\n"
            "请写一条适合直接发在该评论下的回复。"
        ) % (job.get("title") or "未命名", job.get("uname") or "匿名用户", job.get("content"))

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = self._chat(messages)
            text = self._clean_reply(result["text"], max_chars)
            if not text:
                raise LLMError("大模型返回内容为空")
        except LLMError as e:
            self._stats["failed"] += 1
            self._last_error = str(e)
            self.logger.error("评论大模型调用失败: %s" % e)
            self._log_scan("error", "评论 %s 大模型调用失败: %s" % (
                job.get("rpid"), str(e)[:200]))
            fallback = str(cfg.get("fallback_reply") or "").strip()
            self._log_reply(job, fallback, "", int((time.time() - started) * 1000),
                            0, "error: %s" % str(e)[:200])
            if fallback and not self._bool(cfg.get("dry_run")):
                ok, note = self._send_reply(job, fallback)
                if ok:
                    self._stats["replies_sent"] += 1
                    self._log_scan("info", "评论 %s 使用兜底回复发送成功" % job.get("rpid"))
                else:
                    self._stats["failed"] += 1
                    self._log_scan("error", "评论 %s 兜底回复发送失败: %s" % (
                        job.get("rpid"), note))
                self._log_reply(job, fallback, "", int((time.time() - started) * 1000),
                                1 if ok else 0, "fallback_" + note)
            return

        model = result.get("model") or llm.get("model") or ""
        latency = result.get("latency_ms") or int((time.time() - started) * 1000)

        if self._bool(cfg.get("dry_run")):
            self._stats["skipped"] += 1
            self._log_reply(job, text, model, latency, 1, "dry_run")
            self._log_scan("info", "[dry-run] 将回复评论 %s: %s" % (
                job.get("rpid"), text[:80]))
            return

        ok, note = self._send_reply(job, text)
        if ok:
            self._stats["replies_sent"] += 1
            self._log_reply(job, text, model, latency, 1, "sent")
            self._cooldown[str(job.get("mid") or "")] = time.time()
            self._log_scan("info", "已回复评论 %s（%sms）: %s" % (
                job.get("rpid"), latency, text[:80]))
        else:
            self._stats["failed"] += 1
            self._log_reply(job, text, model, latency, 0, note)
            self._log_scan("error", "回复评论 %s 失败: %s" % (job.get("rpid"), note))

    def _send_reply(self, job, text):
        cfg = self._comment_cfg()
        bot = self._find_bot(job.get("account_name"))
        if bot is None:
            return False, "找不到发送账号"

        message = str(text or "").strip()
        if self._bool(cfg.get("prefix_at")) and job.get("uname"):
            message = "@%s %s" % (job["uname"], message)
        message = message[:1000]
        if not message:
            return False, "回复内容为空"

        csrf = str(getattr(bot, "bili_jct", "") or "")
        if not csrf:
            return False, "缺少 bili_jct，无法发送评论"

        video = {
            "type": job.get("type") or 1,
            "oid": job.get("oid") or "",
            "bvid": job.get("bvid") or "",
        }
        # 评论消息可能来自楼中楼：root 必须是根评论，parent 是直接回复的那条评论
        root_rpid = job.get("root_rpid") or job.get("rpid")
        parent_rpid = job.get("parent_rpid") or job.get("rpid")
        form = {
            "type": video["type"],
            "oid": video["oid"],
            "root": root_rpid,
            "parent": parent_rpid,
            "message": message,
            "plat": 1,
            "csrf": csrf,
        }
        headers = self._request_headers(bot, self._video_referer(video))
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        # 控制发送间隔，避免触发 -509
        interval = max(0, self._to_int(cfg.get("send_interval_seconds"), 8))
        wait = interval - (time.time() - self._last_send_at)
        if wait > 0 and self._last_send_at:
            self._stop.wait(min(wait, interval))

        try:
            resp = self.http.session.post(
                ADD_COMMENT_URL, data=form, headers=headers, timeout=20)
        except Exception as e:
            return False, "send_error: %s" % str(e)[:160]

        if resp.status_code != 200:
            return False, "send_http_%s" % resp.status_code
        try:
            data = resp.json()
        except ValueError:
            return False, "send_non_json"

        code = self._to_int(data.get("code"), -1)
        if code != 0:
            reason = REPLY_ERRORS.get(code) or data.get("message") or "未知错误"
            return False, "send_code_%s: %s" % (code, str(reason)[:160])

        self._last_send_at = time.time()
        return True, "sent"

    # ---------- 记录 ----------

    def _log_reply(self, job, answer, model, latency, ok, note):
        self.database.execute(
            "INSERT INTO comment_reply_log "
            "(account, type, oid, title, rpid, mid, uname, question, answer, model, "
            "latency_ms, ok, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.get("account_name") or "", self._to_int(job.get("type"), 1),
             str(job.get("oid") or ""), str(job.get("title") or "")[:200],
             str(job.get("rpid") or ""), str(job.get("mid") or ""),
             str(job.get("uname") or "")[:80], str(job.get("content") or "")[:500],
             str(answer or "")[:1000], str(model or ""), int(latency),
             1 if ok else 0, str(note or "")[:240], time.time()))
        try:
            self.database.execute(
                "DELETE FROM comment_reply_log WHERE id NOT IN "
                "(SELECT id FROM comment_reply_log ORDER BY id DESC LIMIT ?)",
                (MAX_HISTORY_ROWS,))
        except Exception:
            pass

    # ================= 面板 API =================

    def api_config(self, data):
        llm = self._llm_cfg()
        key = llm.pop("api_key", "")
        llm["api_key"] = ""
        llm["api_key_set"] = bool(key)
        comment = self._comment_cfg()
        comment["videos"] = self._normalise_videos(comment.get("videos"))
        return {
            "success": True,
            "llm": llm,
            "comment": comment,
            "stats": self._stats_payload(),
        }

    def api_config_save(self, data):
        current = self.config.get_all() or {}
        llm = dict(current.get("llm") or DEFAULT_CONFIG["llm"])
        comment = dict(current.get("comment") or DEFAULT_CONFIG["comment"])

        incoming_llm = self._p(data, "llm")
        if isinstance(incoming_llm, dict):
            for field in ("base_url", "model", "api_key", "system_prompt"):
                if field not in incoming_llm:
                    continue
                value = str(incoming_llm.get(field) or "").strip()
                if field == "api_key" and (not value or "*" in value):
                    continue  # 留空/掩码（如 sk-xxxx****）表示不修改
                llm[field] = value
            for field, low, high in (("temperature", 0, 2), ("max_tokens", 16, 8192),
                                     ("timeout", 5, 300), ("max_reply_chars", 10, 1000)):
                if field not in incoming_llm or incoming_llm.get(field) in (None, ""):
                    continue
                value = self._to_float(incoming_llm.get(field), 0)
                value = max(low, min(high, value))
                llm[field] = int(value) if field != "temperature" else round(value, 2)
            if llm.get("base_url") and not re.match(r"^https?://", llm["base_url"]):
                raise ValueError("base_url 必须以 http:// 或 https:// 开头")

        incoming_comment = self._p(data, "comment")
        if isinstance(incoming_comment, dict):
            for field in ("enabled", "dry_run", "only_mention", "message_feed",
                          "reply_on_first_scan", "prefix_at", "keyword_only"):
                if field in incoming_comment:
                    comment[field] = self._bool(
                        incoming_comment.get(field), bool(comment.get(field)))
            for field in ("trigger_keywords", "ignore_keywords", "ignore_uids", "accounts"):
                if field in incoming_comment:
                    comment[field] = self._keyword_list(incoming_comment.get(field))
            if "keyword_rules" in incoming_comment:
                comment["keyword_rules"] = self._normalise_keyword_rules(
                    incoming_comment.get("keyword_rules"))
            if "videos" in incoming_comment:
                comment["videos"] = self._normalise_videos(incoming_comment.get("videos"))
            for field, low, high in (
                    ("poll_interval_seconds", 30, 3600),
                    ("send_interval_seconds", 0, 300),
                    ("cooldown_seconds", 0, 86400),
                    ("max_replies_per_day", 0, 100000),
                    ("max_replies_per_scan", 0, 200),
                    ("max_pages_per_scan", 1, 5),
                    ("max_comment_age_seconds", 0, 2592000)):
                if field not in incoming_comment or incoming_comment.get(field) in (None, ""):
                    continue
                value = self._to_int(incoming_comment.get(field), 0)
                comment[field] = max(low, min(high, value))
            if "fallback_reply" in incoming_comment:
                comment["fallback_reply"] = str(
                    incoming_comment.get("fallback_reply") or "").strip()[:300]

        self.config.update({"llm": llm, "comment": comment})
        with self._lock:
            self._cooldown.clear()
        self._video_cache.clear()
        self._ai_fallback_cache = (0, {})
        if comment.get("enabled"):
            self._last_scan_tried = 0  # 开启后尽快扫描一次
        self.logger.info("评论回复配置已更新: enabled=%s, dry_run=%s, videos=%s, 评论消息=%s" % (
            comment.get("enabled"), comment.get("dry_run"),
            len(self._normalise_videos(comment.get("videos"))),
            "开" if self._bool(comment.get("message_feed")) else "关"))
        message = "配置已保存并生效"
        if comment.get("keyword_only") and not comment.get("keyword_rules"):
            message += "；注意：已开启仅关键词模式但没有配置规则，所有评论都会被跳过"
        if (comment.get("enabled") and not self._normalise_videos(comment.get("videos"))
                and not self._bool(comment.get("message_feed"))):
            message += "；注意：尚未配置评论区，也未开启评论消息扫描，不会扫描到任何评论"
        return {
            "success": True,
            "message": message,
            "comment": dict(comment, videos=self._normalise_videos(comment.get("videos"))),
        }

    def api_test(self, data):
        override = self._p(data, "llm")
        try:
            result = self._chat([
                {"role": "system", "content": "你是连接测试助手，只回复一个词。"},
                {"role": "user", "content": "请回复：连接成功"},
            ], override=override if isinstance(override, dict) else None,
                temperature=0.2, max_tokens=32)
        except LLMError as e:
            return {"success": False, "message": str(e)}
        return {"success": True, "message": "连接成功",
                "text": result["text"][:200], "model": result["model"],
                "latency_ms": result["latency_ms"]}

    def _stats_payload(self):
        cfg = self._comment_cfg()
        llm = self._llm_cfg()
        interval = max(30, self._to_int(cfg.get("poll_interval_seconds"), 120))
        next_in = 0
        if cfg.get("enabled") and self._last_scan_tried:
            next_in = max(0, int(interval - (time.time() - self._last_scan_tried)))
        return {
            "ai_calls": self._stats["ai_calls"],
            "scanned": self._stats["scanned"],
            "baseline": self._stats["baseline"],
            "queued": self._stats["queued"],
            "replies_sent": self._stats["replies_sent"],
            "failed": self._stats["failed"],
            "skipped": self._stats["skipped"],
            "replies_today": self._replies_today(),
            "keyword_replies": self._stats.get("keyword_replies", 0),
            "keyword_rules": len(cfg.get("keyword_rules") or []),
            "keyword_only": bool(cfg.get("keyword_only")),
            "last_error": self._last_error,
            "last_scan_at": self._last_scan_at,
            "last_scan_time": time.strftime(
                "%m-%d %H:%M:%S", time.localtime(self._last_scan_at))
            if self._last_scan_at else "",
            "last_scan_duration_ms": self._last_scan_duration,
            "next_scan_in": next_in,
            "enabled": bool(cfg.get("enabled")),
            "dry_run": bool(cfg.get("dry_run")),
            "llm_ready": bool(llm.get("api_key") or self._looks_local(llm.get("base_url"))),
            "model": llm.get("model") or "",
            "max_replies_per_day": self._to_int(cfg.get("max_replies_per_day"), 100),
            "videos": len(self._normalise_videos(cfg.get("videos"))),
            "message_feed": bool(cfg.get("message_feed")),
            "queue_size": self._queue.qsize(),
            "worker_alive": bool(self._worker and self._worker.is_alive()),
            "poller_alive": bool(self._poller and self._poller.is_alive()),
            "scanning": self._scan_lock.locked(),
        }

    def api_stats(self, data):
        return {"success": True, "stats": self._stats_payload()}

    def api_scan(self, data):
        cfg = self._comment_cfg()
        videos = self._normalise_videos(cfg.get("videos"))
        if not videos and not self._bool(cfg.get("message_feed")):
            return {"success": False,
                    "message": "请先配置至少一个评论区，或在面板开启「扫描评论消息（回复我的）」"}
        if self._scan_lock.locked():
            return {"success": False, "message": "正在扫描中，请稍后再试"}
        self._last_scan_tried = time.time()
        threading.Thread(target=self._scan_once, kwargs={"force": True},
                         daemon=True, name="comment-manual-scan").start()
        return {"success": True, "message": "已开始扫描，请稍候查看记录"}

    def api_history(self, data):
        limit = max(1, min(100, self._to_int(self._p(data, "limit"), 20)))
        rows = self.database.fetch_all(
            "SELECT account, type, oid, title, rpid, mid, uname, question, answer, "
            "model, latency_ms, ok, note, created_at "
            "FROM comment_reply_log ORDER BY id DESC LIMIT ?", (limit,))
        items = [{
            "account": row[0], "type": row[1], "oid": row[2], "title": row[3],
            "rpid": row[4], "mid": row[5], "uname": row[6], "question": row[7],
            "answer": row[8], "model": row[9], "latency_ms": row[10],
            "ok": bool(row[11]), "note": row[12], "created_at": row[13],
            "time": time.strftime("%m-%d %H:%M", time.localtime(row[13] or 0)),
        } for row in (rows or [])]
        return {"success": True, "items": items}

    def api_history_clear(self, data):
        self.database.execute("DELETE FROM comment_reply_log")
        self._stats.update({"ai_calls": 0, "replies_sent": 0, "failed": 0,
                            "skipped": 0, "scanned": 0, "queued": 0,
                            "keyword_replies": 0})
        self._last_error = ""
        return {"success": True, "message": "回复记录已清空"}

    def api_seen_clear(self, data):
        self.database.execute("DELETE FROM comment_seen")
        self.database.execute("DELETE FROM comment_scan_state")
        self._last_error = ""
        return {"success": True,
                "message": "已重置扫描基线，下次扫描会重新记录当前评论，不会回复历史评论"}

    # ================= 机器人命令 =================

    def cmd_status(self, message_data, args):
        stats = self._stats_payload()
        lines = [
            "💬 评论区自动回复状态",
            "开关: %s%s" % ("开启" if stats["enabled"] else "关闭",
                          "（预览模式）" if stats["dry_run"] else ""),
            "模型: %s（%s）" % (stats["model"] or "未配置",
                              "可用" if stats["llm_ready"] else "未就绪"),
            "评论区: %s 个，排队: %s 条" % (stats["videos"], stats["queue_size"]),
            "评论消息（回复我的）: %s" % ("开启" if stats["message_feed"] else "关闭"),
            "关键词规则: %s 条%s" % (
                stats["keyword_rules"],
                "（仅关键词模式，未命中不回复）" if stats["keyword_only"] else ""),
            "今日回复: %s 次 / 上限 %s" % (
                stats["replies_today"], stats["max_replies_per_day"]),
            "累计: 成功 %s，失败 %s，跳过 %s" % (
                stats["replies_sent"], stats["failed"], stats["skipped"]),
            "上次扫描: %s" % (stats["last_scan_time"] or "尚未扫描"),
        ]
        if stats["last_error"]:
            lines.append("最近错误: %s" % stats["last_error"][:120])
        return "\n".join(lines)

    def cmd_scan(self, message_data, args):
        cfg = self._comment_cfg()
        if not self._normalise_videos(cfg.get("videos")) and not self._bool(cfg.get("message_feed")):
            return "尚未配置评论区，也未开启评论消息扫描，请先在面板「评论自动回复」中设置"
        if self._scan_lock.locked():
            return "正在扫描中，请稍后再试"
        self._last_scan_tried = time.time()
        threading.Thread(target=self._scan_once, kwargs={"force": True},
                         daemon=True, name="comment-manual-scan").start()
        return "已开始扫描评论区与评论消息，结果会记录在插件日志与面板中"
