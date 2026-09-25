# bilibot_plugins_stats 消息统计插件

记录机器人收到的每条私信消息，提供统计命令、API 接口和面板指标。

## 功能

- 自动记录所有收到的消息（SQLite 存储，数据文件 `plugins/bilibot_plugins_stats/bilibot_plugins_stats.db`）
- 命令 `!stats`：查看总消息数 / 今日消息 / 参与用户数
- API：面板代理访问 `GET /api/plugins/api/bilibot_plugins_stats/stats` 与 `/top`
- 指标：插件详情 → 指标页展示 total_messages / today_messages / unique_users

## 配置

无需配置，开箱即用。
