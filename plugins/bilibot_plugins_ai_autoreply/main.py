# -*- coding: utf-8 -*-
"""
AI 私信自动回复插件
========================================
把原来的「关键词自动回复」升级成「大模型自动回复」：

- 收到私信后调用 OpenAI 兼容接口（DeepSeek / 通义 / Kimi / Ollama / One-API 均可）
- 按用户保存最近若干轮对话，回复能接上下文
- 每个用户独立冷却时间 + 每日回复上限，防止刷屏和被恶意消耗 token
- 支持触发关键词 / 忽略关键词 / 账号白名单
- 支持 dry_run（只记录不发送），方便先观察效果
- 大模型不可用时可选回落固定话术
- 面板接口：配置读写、连接测试、统计、历史记录、清空上下文

与 index.py 的关系
------------------
本插件通过 register_message_handler 注册处理器。真正的生成与发送放在后台线程里，
消息主循环不会被大模型请求阻塞；消息 id 会被标记为已处理，避免每轮轮询重复回复。

面板访问前缀: /api/plugins/api/bilibot_plugins_ai_autoreply
"""
import collections
import json
import queue
import re
import threading
import time

import plugin_dev

DEFAULT_SYSTEM_PROMPT = (
    "你是 B 站 UP 主的私信助理，替主人回复粉丝私信。"
    "请用自然、真诚、口语化的中文回答，句子简短，不要用营销腔，"
    "不要编造主人没有说过的事实，也不要承诺任何无法兑现的事情。"
    "遇到你无法确认的问题，就礼貌说明会让主人本人来回复。"
)

DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.8,
        "max_tokens": 400,
        "timeout": 45,
        "max_reply_chars": 200,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    },
    "reply": {
        "enabled": True,
        "dry_run": False,
        "trigger_keywords": [],
        "ignore_keywords": [],
        "cooldown_seconds": 20,
        "max_replies_per_day": 200,
        "history_turns": 6,
        "accounts": [],
        "fallback_reply": "",
    },
}

# 这些消息内容不是真正的文本，直接忽略
NON_TEXT_HINTS = ("[图片]", "[表情]", "[语音]", "[视频]", "[分享]", "[小程序]")

MAX_QUEUE_SIZE = 200
MAX_HISTORY_ROWS = 2000

# 自己发出消息的"回声"保护窗口（秒）：机器人/AI 刚发出的内容在窗口内再次收到时直接丢弃
SELF_ECHO_WINDOW = 300


class LLMError(Exception):
    """大模型调用异常"""


class Plugin(plugin_dev.APIPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.1"

        self._stats = {
            "ai_calls": 0,
            "replies_sent": 0,
            "failed": 0,
            "skipped": 0,
        }
        self._last_error = ""
        self._last_reply_at = 0
        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._stop = threading.Event()
        self._worker = None
        self._cooldown = {}          # uid -> 上次回复时间戳（内存加速，DB 为准）
        self._lock = threading.Lock()
        # 自己刚发出消息的“回声”记录: (uid, 文本, 时间戳)
        # B 站会话列表会把机器人自己发出的私信再次返回，如果不拦住，
        # AI 会把回复当成粉丝的新提问继续回答，形成自我对话死循环。
        self._sent_echo = collections.deque(maxlen=200)
        self._echo_lock = threading.Lock()

        # 对话上下文
        self.database.create_table("chat_memory", {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "uid": "TEXT",
            "role": "TEXT",
            "content": "TEXT",
            "created_at": "REAL",
        })
        # 回复记录
        self.database.create_table("reply_log", {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "uid": "TEXT",
            "question": "TEXT",
            "answer": "TEXT",
            "model": "TEXT",
            "latency_ms": "INTEGER",
            "ok": "INTEGER",
            "note": "TEXT",
            "created_at": "REAL",
        })
        # 已处理消息去重（重启后仍然生效，防止重复回复）
        self.database.create_table("handled_msg", {
            "key": "TEXT PRIMARY KEY",
            "created_at": "REAL",
        })

        # 注册消息处理器（命令仍由 PluginBase 优先处理）
        self.register_message_handler(self.handle_message)
        self.register_command("ai", self.cmd_ai, "临时调用大模型回复一句话")
        self.register_command("ai_clear", self.cmd_clear, "清空与自己的 AI 对话上下文")
        self.register_command("ai_status", self.cmd_status, "查看 AI 自动回复运行状态")

        # 面板 API
        self.register_api_route("/config", self.api_config)
        self.register_api_route("/config/save", self.api_config_save, methods=["POST"])
        self.register_api_route("/ai/test", self.api_test, methods=["POST"])
        self.register_api_route("/stats", self.api_stats)
        self.register_api_route("/history", self.api_history)
        self.register_api_route("/history/clear", self.api_history_clear, methods=["POST"])
        self.register_api_route("/memory/clear", self.api_memory_clear, methods=["POST"])

        # 插件详情页指标
        self.register_metric("ai_calls", lambda: self._stats["ai_calls"])
        self.register_metric("replies_sent", lambda: self._stats["replies_sent"])
        self.register_metric("failed", lambda: self._stats["failed"])

    # ================= 生命周期 =================

    def on_load(self):
        self._prune_handled()
        cfg = self._llm_cfg()
        reply = self._reply_cfg()
        self._start_worker()
        if not cfg.get("api_key") and not self._looks_local(cfg.get("base_url")):
            self.logger.warning("尚未配置大模型 API Key，AI 回复不可用（可在面板「AI 自动回复」中配置）")
        if not reply.get("enabled"):
            self.logger.info("AI 自动回复处于关闭状态（可在面板开启）")
        else:
            self.logger.info(
                "AI 自动回复已启用: model=%s, 冷却=%ss, 每日上限=%s, dry_run=%s" % (
                    cfg.get("model"), reply.get("cooldown_seconds"),
                    reply.get("max_replies_per_day"), reply.get("dry_run")))

    def on_unload(self):
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=2)
        self._worker = None
        self.logger.info("AI 自动回复插件已卸载")

    # ================= 配置 =================

    def _llm_cfg(self):
        merged = json.loads(json.dumps(DEFAULT_CONFIG["llm"], ensure_ascii=False))
        saved = self.config.get("llm")
        if isinstance(saved, dict):
            merged.update(saved)
        return merged

    def _reply_cfg(self):
        merged = json.loads(json.dumps(DEFAULT_CONFIG["reply"], ensure_ascii=False))
        saved = self.config.get("reply")
        if isinstance(saved, dict):
            merged.update(saved)
        return merged

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
    def _looks_local(base_url):
        base = str(base_url or "")
        return any(host in base for host in ("127.0.0.1", "localhost", "0.0.0.0", "192.168.", "10."))

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

        temp = self._to_float(temperature if temperature is not None else cfg.get("temperature"), 0.8)
        limit = self._to_int(max_tokens if max_tokens is not None else cfg.get("max_tokens"), 400)
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

    def _clean_reply(self, text, max_chars=200):
        text = re.sub(r"^(?:回复|答复|回答)\s*[:：]\s*", "", str(text or "").strip())
        text = text.strip("\"“”'‘’`").strip()
        # 模型偶尔会带 "(笑)" 之类的旁白，保持原样即可，只做长度兜底
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max_chars].rstrip()
        return text

    # ================= 消息处理 =================

    def handle_message(self, message_data):
        """命中条件就丢进后台队列，始终返回 None（不阻塞消息主循环）"""
        try:
            return self._handle_message(message_data)
        except Exception as e:
            self.logger.error("处理私信异常: %s" % e)
            return None

    def _handle_message(self, message_data):
        reply_cfg = self._reply_cfg()
        if not reply_cfg.get("enabled"):
            return None

        content = str(message_data.get("content") or "").strip()
        if not content or content.startswith("!"):
            return None
        if any(hint in content for hint in NON_TEXT_HINTS) and len(content) <= 8:
            return None

        account_name = str(message_data.get("account_name") or "")
        accounts = self._keyword_list(reply_cfg.get("accounts"))
        if accounts and account_name not in accounts:
            return None

        ignores = self._keyword_list(reply_cfg.get("ignore_keywords"))
        if any(word.lower() in content.lower() for word in ignores):
            self.logger.info("命中忽略关键词，跳过: %s" % content[:40])
            return None

        triggers = self._keyword_list(reply_cfg.get("trigger_keywords"))
        if triggers and not any(word.lower() in content.lower() for word in triggers):
            return None

        uid = str(message_data.get("talker_id") or message_data.get("sender_uid") or "")
        if not uid:
            return None

        # 双重自我保护：自己的消息、以及自己刚发出的回复“回声”一律不处理
        own_uid = self._own_uid(account_name)
        if own_uid:
            sender = str(message_data.get("sender_uid") or "").strip()
            talker = str(message_data.get("talker_id") or "").strip()
            if sender == own_uid or talker == own_uid:
                self.logger.info("忽略自己发出的私信（uid=%s）: %s" % (uid, content[:40]))
                return None
        if self._is_echo(uid, content):
            self.logger.info("忽略自己回复的回声（uid=%s）: %s" % (uid, content[:40]))
            return None

        # 去重：同一条私信只处理一次（本插件会自行发送，不靠主循环记忆）
        dedupe_key = "%s:%s" % (account_name, message_data.get("msg_id") or "")
        if message_data.get("msg_id") and self._seen_msg(dedupe_key):
            return None

        if not self._check_cooldown(uid, reply_cfg):
            self._stats["skipped"] += 1
            return None

        if not self._under_daily_limit(reply_cfg):
            self._stats["skipped"] += 1
            self.logger.warning("今日回复已达上限 %s，跳过用户 %s" % (
                reply_cfg.get("max_replies_per_day"), uid))
            return None

        job = {
            "uid": uid,
            "content": content,
            "msg_id": message_data.get("msg_id"),
            "account_name": account_name,
            "received_at": time.time(),
        }
        if message_data.get("msg_id"):
            self._mark_msg(dedupe_key)
        self._touch_cooldown(uid, reply_cfg)
        self._remember_in_bot(account_name, message_data.get("msg_id"))

        try:
            self._queue.put_nowait(job)
        except queue.Full:
            self._stats["skipped"] += 1
            self.logger.warning("AI 回复队列已满，丢弃一条私信")
            return None
        # 告知主循环: 这条私信由插件异步接管, 不要再走关键词/关注检查
        return plugin_dev.SUPPRESS_REPLY

    def _remember_in_bot(self, account_name, msg_id):
        """标记消息已处理，避免 index.py 每轮轮询重复打印/重复进入插件"""
        if not msg_id:
            return
        bot = self._find_bot(account_name)
        if bot is not None and hasattr(bot, "_remember_msg"):
            try:
                bot._remember_msg(msg_id)
            except Exception:
                pass

    def _find_bot(self, account_name):
        bots = list(self.get_bot_accounts() or [])
        for bot in bots:
            if getattr(bot, "account_name", None) == account_name:
                return bot
        return bots[0] if bots else None

    def _own_uid(self, account_name):
        """当前账号自己的 uid（字符串）；取不到时返回空字符串"""
        bots = list(self.get_bot_accounts() or [])
        bot = None
        for item in bots:
            if getattr(item, "account_name", None) == account_name:
                bot = item
                break
        if bot is None and not account_name and len(bots) == 1:
            bot = bots[0]
        if bot is None:
            return ""
        uid = str(getattr(bot, "self_uid", "") or "").strip()
        return "" if uid in ("", "0") else uid

    def _remember_sent(self, uid, text):
        """记录自己刚发出的回复，供回声过滤使用"""
        uid = str(uid or "").strip()
        text = re.sub(r"\s+", "", str(text or ""))
        if not uid or not text:
            return
        with self._echo_lock:
            self._sent_echo.append((uid, text, time.time()))

    def _is_echo(self, uid, content):
        """判断是否为自己刚发出、又被会话列表回传的消息"""
        uid = str(uid or "").strip()
        content = re.sub(r"\s+", "", str(content or ""))
        if not uid or not content:
            return False
        now = time.time()
        with self._echo_lock:
            while self._sent_echo and now - self._sent_echo[0][2] > SELF_ECHO_WINDOW:
                self._sent_echo.popleft()
            for sent_uid, sent_text, _ in self._sent_echo:
                if sent_uid == uid and sent_text == content:
                    return True
        return False

    def _seen_msg(self, key):
        row = self.database.fetch_one(
            "SELECT key FROM handled_msg WHERE key = ?", (key,))
        return bool(row)

    def _mark_msg(self, key):
        self.database.execute(
            "INSERT OR REPLACE INTO handled_msg (key, created_at) VALUES (?, ?)",
            (key, time.time()))

    def _prune_handled(self):
        try:
            self.database.execute(
                "DELETE FROM handled_msg WHERE created_at < ?",
                (time.time() - 3 * 24 * 3600,))
        except Exception as e:
            self.logger.error("清理消息去重表失败: %s" % e)

    # ---------- 限流 ----------

    def _cooldown_left(self, uid, reply_cfg):
        seconds = max(0, self._to_int(reply_cfg.get("cooldown_seconds"), 20))
        if seconds <= 0:
            return 0
        with self._lock:
            last = self._cooldown.get(uid, 0)
        if not last:
            row = self.database.fetch_one(
                "SELECT MAX(created_at) FROM reply_log WHERE uid = ? AND ok = 1", (uid,))
            last = float(row[0]) if row and row[0] else 0
        return max(0, int(seconds - (time.time() - last)))

    def _check_cooldown(self, uid, reply_cfg):
        return self._cooldown_left(uid, reply_cfg) <= 0

    def _touch_cooldown(self, uid, reply_cfg):
        with self._lock:
            self._cooldown[uid] = time.time()
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
            "SELECT COUNT(*) FROM reply_log WHERE ok = 1 AND note = 'sent' AND created_at >= ?",
            (self._day_start(),))
        return int(row[0]) if row else 0

    def _under_daily_limit(self, reply_cfg):
        limit = self._to_int(reply_cfg.get("max_replies_per_day"), 200)
        if limit <= 0:
            return True
        return self._replies_today() < limit

    # ---------- 后台工作线程 ----------

    def _start_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="ai-autoreply")
        self._worker.start()

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                self._process_job(job)
            except Exception as e:
                self.logger.error("AI 回复任务异常: %s" % e)

    def _process_job(self, job):
        reply_cfg = self._reply_cfg()
        llm_cfg = self._llm_cfg()
        uid = job["uid"]
        content = job["content"]
        max_chars = self._to_int(llm_cfg.get("max_reply_chars"), 200)
        temperature = reply_cfg.get("temperature")
        started = time.time()

        messages = [{"role": "system",
                     "content": str(llm_cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)}]
        messages.extend(self._load_memory(uid, self._to_int(reply_cfg.get("history_turns"), 6)))
        messages.append({"role": "user", "content": content})

        try:
            result = self._chat(messages, temperature=temperature)
            text = self._clean_reply(result["text"], max_chars)
            if not text:
                raise LLMError("大模型返回内容为空")
        except LLMError as e:
            self._stats["failed"] += 1
            self._last_error = str(e)
            self.logger.error("大模型调用失败: %s" % e)
            fallback = str(reply_cfg.get("fallback_reply") or "").strip()
            self._log_reply(uid, content, fallback, "", int((time.time() - started) * 1000),
                            0, "error: %s" % str(e)[:200])
            if fallback and not self._bool(reply_cfg.get("dry_run")):
                self._send(job, fallback)
            return

        model = result.get("model") or llm_cfg.get("model") or ""
        latency = result.get("latency_ms") or int((time.time() - started) * 1000)

        if self._bool(reply_cfg.get("dry_run")):
            self._stats["skipped"] += 1
            self._log_reply(uid, content, text, model, latency, 1, "dry_run")
            self.logger.info("[dry-run] 将回复 %s: %s" % (uid, text))
            return

        if self._send(job, text):
            self._stats["replies_sent"] += 1
            self._last_reply_at = time.time()
            self._log_reply(uid, content, text, model, latency, 1, "sent")
            self._append_memory(uid, "user", content)
            self._append_memory(uid, "assistant", text)
            self.logger.info("已回复 %s（%sms）: %s" % (uid, latency, text[:60]))
        else:
            self._stats["failed"] += 1
            self._log_reply(uid, content, text, model, latency, 0, "send_failed")

    def _send(self, job, text):
        bot = self._find_bot(job.get("account_name"))
        if bot is None:
            self.logger.error("发送失败: 找不到账号 %s" % job.get("account_name"))
            return False
        try:
            ok = bool(bot.send_message(int(job["uid"]), text))
        except Exception as e:
            self.logger.error("发送私信异常: %s" % e)
            return False
        if ok:
            # 记下来，稍后会话列表回传这条消息时直接丢弃
            self._remember_sent(job["uid"], text)
        return ok

    # ---------- 上下文 / 记录 ----------

    def _load_memory(self, uid, turns):
        turns = max(0, min(20, turns))
        if turns <= 0:
            return []
        rows = self.database.fetch_all(
            "SELECT role, content FROM chat_memory WHERE uid = ? ORDER BY id DESC LIMIT ?",
            (uid, turns * 2))
        return [{"role": role, "content": content} for role, content in reversed(rows or [])]

    def _append_memory(self, uid, role, content):
        self.database.execute(
            "INSERT INTO chat_memory (uid, role, content, created_at) VALUES (?, ?, ?, ?)",
            (uid, role, content, time.time()))
        row = self.database.fetch_one(
            "SELECT COUNT(*) FROM chat_memory WHERE uid = ?", (uid,))
        total = int(row[0]) if row else 0
        if total > 60:
            self.database.execute(
                "DELETE FROM chat_memory WHERE uid = ? AND id NOT IN "
                "(SELECT id FROM chat_memory WHERE uid = ? ORDER BY id DESC LIMIT 40)",
                (uid, uid))

    def _log_reply(self, uid, question, answer, model, latency, ok, note):
        self.database.execute(
            "INSERT INTO reply_log (uid, question, answer, model, latency_ms, ok, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, str(question)[:500], str(answer)[:1000], str(model), int(latency),
             1 if ok else 0, str(note), time.time()))
        try:
            self.database.execute(
                "DELETE FROM reply_log WHERE id NOT IN "
                "(SELECT id FROM reply_log ORDER BY id DESC LIMIT ?)", (MAX_HISTORY_ROWS,))
        except Exception:
            pass

    # ================= 面板 API =================

    def api_config(self, data):
        llm = self._llm_cfg()
        key = llm.pop("api_key", "")
        llm["api_key"] = ""
        llm["api_key_set"] = bool(key)
        reply = self._reply_cfg()
        return {
            "success": True,
            "llm": llm,
            "reply": reply,
            "stats": self._stats_payload(),
        }

    def api_config_save(self, data):
        current = self.config.get_all() or {}
        llm = dict(current.get("llm") or DEFAULT_CONFIG["llm"])
        reply = dict(current.get("reply") or DEFAULT_CONFIG["reply"])

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

        incoming_reply = self._p(data, "reply")
        if isinstance(incoming_reply, dict):
            for field in ("enabled", "dry_run"):
                if field in incoming_reply:
                    reply[field] = self._bool(incoming_reply.get(field), bool(reply.get(field)))
            for field in ("trigger_keywords", "ignore_keywords", "accounts"):
                if field in incoming_reply:
                    reply[field] = self._keyword_list(incoming_reply.get(field))
            for field, low, high in (("cooldown_seconds", 0, 3600),
                                     ("max_replies_per_day", 0, 100000),
                                     ("history_turns", 0, 20)):
                if field not in incoming_reply or incoming_reply.get(field) in (None, ""):
                    continue
                value = self._to_int(incoming_reply.get(field), 0)
                reply[field] = max(low, min(high, value))
            if "fallback_reply" in incoming_reply:
                reply["fallback_reply"] = str(incoming_reply.get("fallback_reply") or "").strip()[:300]

        self.config.update({"llm": llm, "reply": reply})
        with self._lock:
            self._cooldown.clear()
        self.logger.info("AI 回复配置已更新: enabled=%s, dry_run=%s" % (
            reply.get("enabled"), reply.get("dry_run")))
        return {"success": True, "message": "配置已保存并生效"}

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
        reply_cfg = self._reply_cfg()
        llm_cfg = self._llm_cfg()
        return {
            "ai_calls": self._stats["ai_calls"],
            "replies_sent": self._stats["replies_sent"],
            "failed": self._stats["failed"],
            "skipped": self._stats["skipped"],
            "replies_today": self._replies_today(),
            "last_error": self._last_error,
            "last_reply_at": self._last_reply_at,
            "enabled": bool(reply_cfg.get("enabled")),
            "dry_run": bool(reply_cfg.get("dry_run")),
            "llm_ready": bool(llm_cfg.get("api_key") or self._looks_local(llm_cfg.get("base_url"))),
            "model": llm_cfg.get("model") or "",
            "queue_size": self._queue.qsize(),
            "worker_alive": bool(self._worker and self._worker.is_alive()),
        }

    def api_stats(self, data):
        return {"success": True, "stats": self._stats_payload()}

    def api_history(self, data):
        limit = max(1, min(100, self._to_int(self._p(data, "limit"), 20)))
        rows = self.database.fetch_all(
            "SELECT uid, question, answer, model, latency_ms, ok, note, created_at "
            "FROM reply_log ORDER BY id DESC LIMIT ?", (limit,))
        items = [{
            "uid": row[0], "question": row[1], "answer": row[2], "model": row[3],
            "latency_ms": row[4], "ok": bool(row[5]), "note": row[6],
            "created_at": row[7],
            "time": time.strftime("%m-%d %H:%M", time.localtime(row[7] or 0)),
        } for row in (rows or [])]
        return {"success": True, "items": items}

    def api_history_clear(self, data):
        self.database.execute("DELETE FROM reply_log")
        self._stats.update({"ai_calls": 0, "replies_sent": 0, "failed": 0, "skipped": 0})
        self._last_error = ""
        return {"success": True, "message": "回复记录已清空"}

    def api_memory_clear(self, data):
        uid = str(self._p(data, "uid") or "").strip()
        if uid:
            self.database.execute("DELETE FROM chat_memory WHERE uid = ?", (uid,))
            return {"success": True, "message": "已清空该用户的对话上下文"}
        self.database.execute("DELETE FROM chat_memory")
        return {"success": True, "message": "已清空全部对话上下文"}

    # ================= 机器人命令 =================

    def cmd_ai(self, message_data, args):
        text = (args or "").strip()
        if not text:
            return "用法：!ai 想说的话，例如 !ai 今天直播几点开始"
        try:
            result = self._chat([
                {"role": "system",
                 "content": str(self._llm_cfg().get("system_prompt") or DEFAULT_SYSTEM_PROMPT)},
                {"role": "user", "content": text},
            ], temperature=0.3, max_tokens=300)
        except LLMError as e:
            return "AI 调用失败：%s" % e
        return self._clean_reply(result["text"], 400)

    def cmd_clear(self, message_data, args):
        uid = str(message_data.get("talker_id") or message_data.get("sender_uid") or "")
        if not uid:
            return "无法识别你的用户 ID"
        self.database.execute("DELETE FROM chat_memory WHERE uid = ?", (uid,))
        return "已清空我们之间的 AI 对话上下文"

    def cmd_status(self, message_data, args):
        stats = self._stats_payload()
        lines = [
            "🤖 AI 自动回复状态",
            "开关: %s%s" % ("开启" if stats["enabled"] else "关闭",
                          "（预览模式）" if stats["dry_run"] else ""),
            "模型: %s（%s）" % (stats["model"] or "未配置",
                              "可用" if stats["llm_ready"] else "未就绪"),
            "今日回复: %s 次 / 上限 %s" % (
                stats["replies_today"], self._reply_cfg().get("max_replies_per_day")),
            "累计: 成功 %s，失败 %s，跳过 %s" % (
                stats["replies_sent"], stats["failed"], stats["skipped"]),
        ]
        if stats["last_error"]:
            lines.append("最近错误: %s" % stats["last_error"][:120])
        return "\n".join(lines)
