# bilibot_plugins_schedule 定时任务插件

按配置定时给指定用户发送消息（如整点提醒、直播通知等）。

## 功能

- 从 `config.json` 读取任务列表，加载时自动注册定时器
- 命令 `!tasks`：查看当前任务
- API：`GET /api/plugins/api/bilibot_plugins_schedule/tasks`
- 卸载/重载插件时自动停止所有定时线程（不会残留后台任务）

## 配置

在面板「插件详情 → 配置」中编辑：

```json
{
    "tasks": [
        {
            "name": "整点提醒",          // 任务名称
            "interval_minutes": 60,      // 间隔分钟数
            "message": "提醒内容",        // 发送的文本
            "receiver_id": 123456        // 接收者 UID（0 表示跳过）
        }
    ]
}
```

保存后插件自动重载并生效。注意定时任务从插件加载时开始计时（首次执行在第一个周期后）。
