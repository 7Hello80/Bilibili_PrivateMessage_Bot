# bilibot_plugins_comment_autoreply — 评论区 AI 自动回复

定时扫描 B 站**视频 / 动态 / 专栏**评论区，把新评论交给大模型生成回复并发送。
接口实现参考 [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)：

| 用途 | 接口 |
| --- | --- |
| 获取评论列表 | `GET https://api.bilibili.com/x/v2/reply`（`type` + `oid`，默认按时间，接口返回空时自动回退按点赞） |
| 发表评论 | `POST https://api.bilibili.com/x/v2/reply/add`（`type`、`oid`、`root`、`parent`、`message`、`csrf`） |
| BV 转 aid / 补全标题 | `GET https://api.bilibili.com/x/web-interface/view` |

`type` 取值：`1` 视频、`12` 专栏、`17` 动态。

## 功能

- **接大模型**：任意 OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、Ollama、One-API、OpenAI）
- **多评论区**：每个评论区可单独指定由哪个账号回复
- **基线保护**：首次扫描只记录当前评论作为基线，不会把历史评论全部回一遍
- **过滤规则**：触发关键词 / 忽略关键词 / 忽略用户 / 只回复 @UP 或命中关键词
- **防刷保护**：同一用户冷却、每日总量上限、单次扫描上限、每区翻页上限、评论时效限制
- **发送节流**：两条评论之间自动等待 `send_interval_seconds`，降低 `-509 / 风控` 概率
- **预览模式**：`dry_run` 只生成并记录，不真正发评论，建议先观察
- **兜底话术**：大模型不可用时可选发固定回复（默认不发）
- **面板页面**：`评论自动回复` 页可配置、测试连通性、立即扫描、重置基线、查看记录
- **私信命令**
  - `!comment_status`：查看开关、模型、今日用量与最近错误
  - `!comment_scan`：立即扫描一次

## 配置说明

面板「评论自动回复」页保存后立即生效（机器人运行中会热重载插件）。也可以直接编辑
`plugins/bilibot_plugins_comment_autoreply/config.json`：

```json
{
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-xxx",
        "model": "deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 300,
        "timeout": 45,
        "max_reply_chars": 150,
        "system_prompt": "你是 B 站 UP 主的评论区助理……"
    },
    "comment": {
        "enabled": true,
        "dry_run": false,
        "poll_interval_seconds": 120,
        "send_interval_seconds": 8,
        "videos": [
            "BV1xx411c7mD",
            "12|123456|某篇专栏",
            "17|987654321|一条动态|主账号"
        ],
        "accounts": [],
        "only_mention": false,
        "trigger_keywords": [],
        "ignore_keywords": ["广告", "互关"],
        "ignore_uids": [],
        "cooldown_seconds": 60,
        "max_replies_per_day": 100,
        "max_replies_per_scan": 20,
        "max_pages_per_scan": 2,
        "max_comment_age_seconds": 604800,
        "reply_on_first_scan": false,
        "prefix_at": false,
        "fallback_reply": ""
    }
}
```

### 评论区写法（`videos`）

每行一个，支持以下三种写法：

| 写法 | 示例 | 说明 |
| --- | --- | --- |
| 直接填 ID / 链接 | `BV1xx411c7mD`、`av12345`、`cv123456`、`https://t.bilibili.com/987654321` | 自动识别类型 |
| 带类型 | `1\|170001`、`12\|123456`、`17\|987654321` | 类型 1 视频 / 12 专栏 / 17 动态 |
| 完整写法 | `1\|BV1xx411c7mD\|视频标题\|主账号` | 标题与账号可省略，账号对应「多账号管理」中的名称 |

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `llm.base_url` | 填到 `/v1` 即可，插件自动拼接 `/chat/completions`；留空且 `api_key` 为空时复用「AI 自动回复」页的配置 |
| `llm.max_reply_chars` | 回复正文长度上限（字符） |
| `comment.poll_interval_seconds` | 扫描间隔，最小 30 秒，建议 ≥ 120 秒 |
| `comment.send_interval_seconds` | 两条评论的发送间隔，建议 ≥ 5 秒 |
| `comment.only_mention` | 只回复含 `@昵称` 或命中触发关键词的评论 |
| `comment.reply_on_first_scan` | 首次扫描是否也回复历史评论（默认关闭） |
| `comment.prefix_at` | 回复正文前加 `@评论者昵称` |
| `comment.trigger_keywords` | 留空表示所有评论都回复；填写后只回复命中这些词的评论 |
| `comment.ignore_keywords` | 命中则不回复 |
| `comment.ignore_uids` | 忽略的用户 UID 列表 |
| `comment.cooldown_seconds` | 同一用户两次自动回复的最小间隔 |
| `comment.max_replies_per_day` | 每日发送上限，`0` 表示不限 |
| `comment.max_replies_per_scan` | 单次扫描最多回复条数 |
| `comment.max_pages_per_scan` | 每个评论区每次最多翻页数（每页 20 条） |
| `comment.max_comment_age_seconds` | 只回复该时间内的评论，`0` 表示不限 |
| `comment.fallback_reply` | 大模型失败时的兜底话术，留空则不发送 |

## 行为说明

- 只回复**一级评论**，不进入楼中楼，避免刷屏。
- 评论在「处理后」写入 `comment_seen` 去重：被跳过（关键词、冷却、限额）的评论也不会再次处理。
- 首次扫描或「重置扫描基线」后，只记录当前评论，不会回复历史评论。
- 发送失败会记录 B 站错误码含义（如 `-509` 请求过于频繁、`12051` 重复评论）。
- 数据保存在 `plugins/bilibot_plugins_comment_autoreply/*.db`（已 gitignore）。

## 风险提示

- B 站对评论区有频率限制和风控，请**先开预览模式**观察回复质量，再逐步放开。
- 匿名/无 Cookie 请求下「按时间排序」经常返回空列表（`code=0` 但无数据），插件会自动回退到按点赞排序并在日志中提示；此时顺序不再严格按时间，翻页上限 `max_pages_per_scan` 仍会生效。
- 建议 `send_interval_seconds ≥ 5`、`max_replies_per_day` 不要设置过大。
- 大模型可能生成不当内容，出错会造成真实评论，请务必配置好 `system_prompt` 与忽略关键词。
