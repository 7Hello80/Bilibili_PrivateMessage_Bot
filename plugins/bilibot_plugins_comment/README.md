# 评论区管理插件（bilibot_plugins_comment）

在面板中浏览、回复、点赞、删除 B 站评论，并可选接入大模型实现「AI 生成回复」「AI 评论摘要」「自动回复新评论」。

> 使用前提：机器人进程正在运行。插件通过面板 `plugin_bridge` 的 `/api/plugins/api/...` 代理暴露接口，账号 Cookie 直接复用机器人实例；机器人未运行时回退读取 `config.json`（仅 SESSDATA / bili_jct）。

## 面板入口

侧边栏「内容与扩展 → 评论区管理」。

1. 输入 BV 号、av 号、视频链接、b23.tv 短链，或直接输入评论区 oid（非视频类型需同时选择类型）。
2. 选择账号与排序后点击「加载评论」。
3. 每条评论支持：点赞/取消、回复、AI 生成回复、删除（仅自己发表的）、展开子回复。
4. 右侧「AI 评论摘要」会对当前排序下最多 120 条评论做采样总结（结果缓存 5 分钟）。
5. 右上角「AI 设置」配置大模型与自动回复。

## 配置说明

配置文件：`plugins/bilibot_plugins_comment/config.json`（已被 `.gitignore` 忽略，参考 `config.example.json`）。

```jsonc
{
  "llm": {
    "base_url": "https://api.openai.com/v1",  // 兼容 OpenAI Chat Completions
    "api_key": "",                             // 仅保存在本机，接口返回时脱敏
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 512,
    "timeout": 60,
    "max_reply_chars": 120,                    // 生成回复的字数上限提示
    "system_prompt": "你是熟悉 B 站社区文化的评论区助理……"
  },
  "auto_reply": {
    "enabled": false,          // 默认关闭
    "oid": "",                 // BV 号 / av 号 / 链接 / oid
    "type": 1,
    "interval_minutes": 10,    // 轮询间隔（最小 2 分钟）
    "max_per_run": 2,          // 每轮最多回复几条（1-10）
    "dry_run": true,           // 默认只记录不发送
    "skip_up_replied": true,   // 跳过 UP 主已回复过的评论
    "style": "友好",
    "extra_prompt": ""
  },
  "default_type": 1,
  "default_target": "",
  "accounts_index": 0
}
```

`base_url` 只需填到 `/v1`，插件会自动拼接 `/chat/completions`；也可直接填完整的 `.../chat/completions`。

### 自动回复安全策略

- 默认 `enabled=false`，且开启后 `dry_run=true` 只写日志不发送。
- 首次绑定某个评论区（或更换目标）时，会把当前最新 20 条评论标记为已读，**不会回复历史评论**。
- 每轮最多回复 `max_per_run` 条；生成或发送失败会中止本轮，等待下一轮。
- 建议先观察 `plugin.log` 中的 `[dry-run] 将回复 ...`，确认语气无误后再关闭 dry_run。

## 机器人命令

| 命令 | 说明 |
| --- | --- |
| `!cmt BV号 / av号 / 链接 / oid [类型代码]` | 返回评论区总数与 5 条高赞评论 |
| `!ai 想回复的内容` | 调用大模型生成一段不超过 120 字的回复 |

## HTTP 接口

均以 `/api/plugins/api/bilibot_plugins_comment` 为前缀，需面板登录。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/accounts` | 可用账号列表 |
| GET | `/comments?target=&type=&pn=&ps=&sort=&nohot=&account=` | 评论列表（含热评/置顶） |
| GET | `/replies?target=&type=&root=&pn=` | 指定根评论的子回复 |
| POST | `/add` | `{target,type,message,root?,parent?,account?}` 发表/回复 |
| POST | `/action` | `{target,type,rpid,action}` 点赞(1)/取消(0) |
| POST | `/delete` | `{target,type,rpid}` 删除自己的评论 |
| POST | `/ai/reply` | `{message,uname?,title?,style?,extra?}` 生成回复 |
| POST | `/ai/summary` | `{target,type,sort?,limit?}` 评论摘要 |
| POST | `/ai/test` | 测试大模型连接（可传 `llm` 覆盖保存值） |
| GET | `/config` | 读取配置（API Key 脱敏） |
| POST | `/config/save` | 保存配置并重载自动回复线程 |
| GET | `/history?limit=` | 最近操作记录 |
| GET | `/stats` | 计数指标 |

## 数据与指标

- SQLite：`plugins/bilibot_plugins_comment/bilibot_plugins_comment.db`
  - `comment_log`：发表/回复/点赞/删除/自动回复预览
  - `auto_seen`：自动回复已读 rpid
  - `kv`：自动回复绑定目标
- 指标：`comments_fetched`、`replies_posted`、`ai_calls`（面板插件详情 → 指标）。

## 常见错误

| code | 含义 |
| --- | --- |
| -101 | 账号未登录 / SESSDATA 失效 |
| -111 | csrf 校验失败（bili_jct 失效） |
| 12002 | 评论区已关闭 |
| 12009 | 评论区类型不合法 |
| 12015 | 需要验证码（请先在网页端完成验证） |
| 12035 | 被 UP 主拉黑 |
| 12051 | 重复评论 / 刷屏限制 |

B 站对评论频率与内容审核较严格，请控制发送频率，避免账号风控。
