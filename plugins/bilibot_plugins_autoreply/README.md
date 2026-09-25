# bilibot_plugins_autoreply 增强自动回复插件

可配置关键词回复规则 + 每用户冷却防刷，且**未关注用户也能收到回复**（声明了 `bypass_follow_check: true`）。

## 功能

- 从 `config.json` 读取规则列表，每条规则支持用 `;` 分隔多个关键词
- 每个用户 + 每条规则独立冷却时间，避免刷屏
- 命令 `!rules`：查看当前规则

## 配置

在面板「插件详情 → 配置」中编辑：

```json
{
    "rules": [
        {
            "keyword": "你好;在吗;hello",   // 命中任一关键词即回复
            "reply": "你好呀~",             // 回复内容
            "cooldown_seconds": 60          // 同一用户冷却秒数
        }
    ]
}
```

保存后插件自动重载并生效。
