# bilibot_plugins_ai_autoreply — AI 私信自动回复

把原本的关键词自动回复升级为「大模型自动回复」：粉丝发来私信后，插件调用 OpenAI 兼容接口生成回复并直接发送。

## 功能

- **接大模型**：任何 OpenAI 兼容接口都能用（DeepSeek、通义千问、Kimi、智谱、Ollama、One-API、OpenAI）
- **上下文记忆**：按用户保存最近 N 轮对话，追问也能接上
- **防刷保护**：同一用户冷却时间 + 每日回复总量上限
- **可控范围**：触发关键词 / 忽略关键词 / 生效账号白名单
- **预览模式**：`dry_run` 只生成并记录，不真正发送，先观察效果再开启
- **异步发送**：大模型请求在后台线程执行，不会卡住私信轮询
- **面板页面**：`AI 自动回复` 页可配置模型、测试连通性、查看回复记录
- **兜底话术**：大模型不可用时可选发送固定回复（默认不发，避免故障刷屏）
- **私信命令**
  - `!ai <内容>`：临时让大模型生成一段回复
  - `!ai_status`：查看开关、模型、今日用量与错误
  - `!ai_clear`：清空与自己的对话上下文

## 配置说明

面板「AI 自动回复」页保存后立即生效（机器人运行中会热重载插件）。也可以直接编辑
`plugins/bilibot_plugins_ai_autoreply/config.json`：

```json
{
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-xxx",
        "model": "deepseek-chat",
        "temperature": 0.8,
        "max_tokens": 400,
        "timeout": 45,
        "max_reply_chars": 200,
        "system_prompt": "你是 B 站 UP 主的私信助理……"
    },
    "reply": {
        "enabled": true,
        "dry_run": false,
        "trigger_keywords": [],
        "ignore_keywords": ["广告", "互关"],
        "cooldown_seconds": 20,
        "max_replies_per_day": 200,
        "history_turns": 6,
        "accounts": [],
        "fallback_reply": ""
    }
}
```

| 字段 | 说明 |
| --- | --- |
| `llm.base_url` | 填到 `/v1` 即可，插件自动拼接 `/chat/completions`；本地 Ollama 填 `http://127.0.0.1:11434/v1` |
| `llm.api_key` | 本地服务可留空 |
| `llm.max_reply_chars` | 回复正文长度上限（字符） |
| `reply.trigger_keywords` | 留空表示所有私信都回复；填写后只回复命中这些词的私信 |
| `reply.ignore_keywords` | 命中则不回复 |
| `reply.cooldown_seconds` | 同一用户两次自动回复的最小间隔 |
| `reply.max_replies_per_day` | 每日发送上限，`0` 表示不限 |
| `reply.history_turns` | 携带的上下文轮数，`0` 表示不带历史 |
| `reply.accounts` | 生效账号名称列表，留空表示全部账号 |
| `reply.fallback_reply` | 大模型失败时的兜底话术，留空则不发送 |

## 行为说明

- 自动回复**不受「必须关注」限制**（`package.json` 中 `bypass_follow_check: true`），
  需要限制可在「忽略关键词 / 触发关键词」中控制。
- 同一条私信只会处理一次（消息 id 落库去重）。
- 处理完成后插件返回 `plugin_dev.SUPPRESS_REPLY`，主循环不会再走关键词回复，
  因此不会出现「AI 回复 + 关键词回复」两条消息。
- 与 `bilibot_plugins_autoreply`（关键词插件）同时启用时，AI 插件先命中并接管，
  关键词插件不会重复回复同一条私信。
- 回复记录、上下文与去重数据保存在 `plugins/bilibot_plugins_ai_autoreply/*.db`（已 gitignore）。

## 常见问题

**「未配置 / 未就绪」**：检查 `base_url`、`model`、`api_key`，点「测试连接」看具体报错。

**回复很慢**：模型首字延迟通常在 1~5 秒；`timeout` 不要设太小，否则会被判定失败。

**被 B 站限制频率**：调大 `cooldown_seconds`、调小 `max_replies_per_day`，并避免 `dry_run: false` 下高频对外发送。
