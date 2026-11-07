# bilibot_plugins_comment_autoreply — 评论区 AI 自动回复

定时扫描 B 站**视频 / 动态 / 专栏**评论区，也可以不配置任何评论区，直接从消息中心
「回复我的」里扫描 @我 / 回复我的评论，把新评论交给大模型生成回复并发送。
接口实现参考 [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)：

| 用途 | 接口 |
| --- | --- |
| 获取评论列表 | `GET https://api.bilibili.com/x/v2/reply`（`type` + `oid`，默认按时间，接口返回空时自动回退按点赞） |
| 发表评论 | `POST https://api.bilibili.com/x/v2/reply/add`（`type`、`oid`、`root`、`parent`、`message`、`csrf`） |
| 回复我的消息 | `GET https://api.bilibili.com/x/msgfeed/reply`（消息中心「回复我的」） |
| BV 转 aid / 补全标题 | `GET https://api.bilibili.com/x/web-interface/view` |

`type` 取值：`1` 视频、`12` 专栏、`17` 动态。

## 功能

- **接大模型**：任意 OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、Ollama、One-API、OpenAI）
- **关键词规则**：命中自定义关键词时直接发送固定内容、不调用大模型；可开启「仅关键词模式」完全关闭大模型
- **多种扫描来源**：既可按配置扫描多个评论区（视频 BV/av、动态、专栏），也可以只扫描「回复我的」评论消息
- **消息中心扫描**：开启 `message_feed` 后从消息中心读取 @我 / 回复我的评论，自动识别视频、动态、专栏；楼中楼 @ 也能按原楼层回复
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
        "message_feed": true,
        "accounts": [],
        "only_mention": false,
        "trigger_keywords": [],
        "ignore_keywords": ["广告", "互关"],
        "ignore_uids": [],
        "keyword_rules": [
            {
                "keywords": ["求教程", "怎么学"],
                "reply": "@{nick} 教程在《{title}》里～",
                "match": "contains"
            },
            {
                "keywords": ["已三连"],
                "reply": "感谢三连！",
                "match": "exact"
            }
        ],
        "keyword_only": false,
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

### 扫描来源一：评论区（`videos`）

每行一个，支持以下三种写法：

| 写法 | 示例 | 说明 |
| --- | --- | --- |
| 直接填 ID / 链接 | `BV1xx411c7mD`、`av12345`、`cv123456`、`https://t.bilibili.com/987654321` | 自动识别类型 |
| 带类型 | `1\|170001`、`12\|123456`、`17\|987654321` | 类型 1 视频 / 12 专栏 / 17 动态 |
| 完整写法 | `1\|BV1xx411c7mD\|视频标题\|主账号` | 标题与账号可省略，账号对应「多账号管理」中的名称 |

### 扫描来源二：评论消息（`message_feed`）

开启 `comment.message_feed` 后，插件会读取消息中心的「回复我的」，**不需要配置 `videos`**：

- 包括别人在视频、动态、专栏评论区 **@你**，以及**直接回复你的评论**（含楼中楼）
- 自动从消息中的 `uri` / `business_id` 识别评论类型与 `oid`，视频消息还能反查标题用于占位符 `{title}`
- 楼中楼回复会带上原楼层 `root` / `parent`，回复在该楼层下，不会另起一条一级评论
- 这些消息本身就是针对本账号的，因此**不受** `only_mention` 与 `trigger_keywords` 限制；但忽略关键词、忽略用户、冷却、每日上限、评论时效、`keyword_only` 仍然生效
- 首次扫描（或「重置基线」后）只记录当前消息作为基线，不会回复历史消息；此后只回复新出现的通知
- 去重键为 `msgfeed:<UID>:<rpid>`，同一评论从评论区与消息中心只会处理一次

`videos` 与 `message_feed` 可以同时开启：消息中心负责「@我 / 回复我」，`videos` 负责其他普通评论。

### 关键词规则（`keyword_rules`）

面板里每行一条，格式为 `关键词1;关键词2 => 回复内容`：

- 关键词之间用 `;`、`，` 或 `,` 分隔，**命中任意一个即可**
- 行首加 `=` 表示整条评论完全相等才命中，否则为「包含」匹配
- `#` 开头的行为注释
- 支持占位符：`{nick}` / `{uname}` / `{user}`（评论者昵称）、`{title}`（评论区标题）
- 规则按从上到下的顺序匹配，命中第一条即回复，不再调用大模型
- 每条规则最多 20 个关键词（每个 ≤ 40 字），回复正文 ≤ 500 字，最多 100 条规则

```
求教程;怎么学 => @{nick} 教程在《{title}》里～
=已三连 => 感谢三连！
# 这一行是注释
```

配置文件中同样支持上述多行文本写法，或使用结构化写法：

```json
{"keywords": ["求教程", "怎么学"], "reply": "@{nick} 教程在《{title}》里～", "match": "contains"}
```

开启 `keyword_only` 后完全不调用大模型：命中规则的评论发固定内容，未命中的评论直接跳过。
关键词规则命中同样受发送间隔、用户冷却、每日上限与预览模式约束。

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `llm.base_url` | 填到 `/v1` 即可，插件自动拼接 `/chat/completions`；留空且 `api_key` 为空时复用「AI 自动回复」页的配置 |
| `llm.max_reply_chars` | 回复正文长度上限（字符） |
| `comment.poll_interval_seconds` | 扫描间隔，最小 30 秒，建议 ≥ 120 秒 |
| `comment.send_interval_seconds` | 两条评论的发送间隔，建议 ≥ 5 秒 |
| `comment.message_feed` | 扫描消息中心「回复我的」，不配置 `videos` 也能回复 @我 / 回复我的评论 |
| `comment.only_mention` | 只回复含 `@昵称` 或命中触发关键词的评论（仅对评论区扫描生效） |
| `comment.reply_on_first_scan` | 首次扫描是否也回复历史评论（默认关闭） |
| `comment.prefix_at` | 回复正文前加 `@评论者昵称` |
| `comment.trigger_keywords` | 留空表示所有评论都回复；填写后只回复命中这些词的评论 |
| `comment.ignore_keywords` | 命中则不回复 |
| `comment.ignore_uids` | 忽略的用户 UID 列表 |
| `comment.keyword_rules` | 关键词 → 固定回复规则，命中后不调用大模型（写法见上） |
| `comment.keyword_only` | 仅关键词模式：不调用大模型，未命中规则的评论不回复 |
| `comment.cooldown_seconds` | 同一用户两次自动回复的最小间隔 |
| `comment.max_replies_per_day` | 每日发送上限，`0` 表示不限 |
| `comment.max_replies_per_scan` | 单次扫描最多回复条数 |
| `comment.max_pages_per_scan` | 每个评论区每次最多翻页数（每页 20 条） |
| `comment.max_comment_age_seconds` | 只回复该时间内的评论，`0` 表示不限 |
| `comment.fallback_reply` | 大模型失败时的兜底话术，留空则不发送 |

## 行为说明

- 评论区扫描只回复**一级评论**，不进入楼中楼，避免刷屏；从「评论消息」扫描到的楼中楼 @我 / 回复我 会按原楼层回复。
- 评论在「处理后」写入 `comment_seen` 去重：被跳过（关键词、冷却、限额）的评论也不会再次处理。同一条评论即使同时出现在评论区和消息中心，也只会处理一次。
- 首次扫描或「重置扫描基线」后，只记录当前评论，不会回复历史评论。消息中心按账号单独记录基线（`msgfeed:<UID>`）。
- 命中关键词规则的评论会直接发送固定内容，历史记录中标记为 `keyword`，并计入「关键词回复」统计；预览模式下只记录不发送。
- 每轮扫描先处理评论消息，再处理 `videos`；消息中心失败（如 Cookie 失效）只记录错误，不影响评论区扫描。
- 发送失败会记录 B 站错误码含义（如 `-509` 请求过于频繁、`12051` 重复评论）。
- 数据保存在 `plugins/bilibot_plugins_comment_autoreply/*.db`（已 gitignore）。

## 风险提示

- B 站对评论区有频率限制和风控，请**先开预览模式**观察回复质量，再逐步放开。
- 匿名/无 Cookie 请求下「按时间排序」经常返回空列表（`code=0` 但无数据），插件会自动回退到按点赞排序并在日志中提示；此时顺序不再严格按时间，翻页上限 `max_pages_per_scan` 仍会生效。
- 建议 `send_interval_seconds ≥ 5`、`max_replies_per_day` 不要设置过大。
- 大模型可能生成不当内容，出错会造成真实评论，请务必配置好 `system_prompt` 与忽略关键词。
