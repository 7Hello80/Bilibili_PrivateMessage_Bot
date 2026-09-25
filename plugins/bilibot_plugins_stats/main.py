# -*- coding: utf-8 -*-
"""
消息统计插件
- 记录每条收到的消息到 SQLite
- 命令: !stats 查看统计
- API: /stats 统计概览, /top 活跃用户排行
- 指标: total_messages / today_messages / unique_users (面板"指标"页可见)
"""
import plugin_dev
import time
from datetime import datetime, timedelta


class Plugin(plugin_dev.AnalysisPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"

        # 建表
        self.database.create_table('message_log', {
            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
            'sender_uid': 'TEXT',
            'content': 'TEXT',
            'created_at': 'TEXT'
        })

        # 注册事件: 每条收到的消息都会触发
        self.register_event_handler('message_received', self.on_message_received)

        # 注册命令
        self.register_command('stats', self.cmd_stats, '查看消息统计')

        # 注册 API 路由(面板访问: /api/plugins/api/bilibot_plugins_stats/stats)
        self.register_api_route('/stats', self.api_stats)
        self.register_api_route('/top', self.api_top)

        # 注册指标(面板插件详情-指标页展示)
        self.register_metric('total_messages', self.metric_total)
        self.register_metric('today_messages', self.metric_today)
        self.register_metric('unique_users', self.metric_users)

    def on_load(self):
        self.logger.info(f"消息统计插件 {self.name} 加载成功")

    def on_unload(self):
        self.logger.info(f"消息统计插件 {self.name} 卸载成功")

    # ============ 事件处理 ============

    def on_message_received(self, message_data):
        sender_uid = str(message_data.get('sender_uid', ''))
        content = message_data.get('content', '')
        try:
            with self.database as conn:
                conn.execute(
                    'INSERT INTO message_log (sender_uid, content, created_at) VALUES (?, ?, ?)',
                    (sender_uid, content, self.utils.format_time()))
        except Exception as e:
            self.logger.error(f"写入消息记录失败: {str(e)}")

    # ============ 命令处理 ============

    def cmd_stats(self, message_data, args):
        total = self.database.fetch_one('SELECT COUNT(*) FROM message_log')
        today = self.database.fetch_one(
            "SELECT COUNT(*) FROM message_log WHERE created_at >= ?",
            ((datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),))
        users = self.database.fetch_one('SELECT COUNT(DISTINCT sender_uid) FROM message_log')
        return (f"📊 消息统计\n"
                f"总消息数: {total[0] if total else 0}\n"
                f"今日消息: {today[0] if today else 0}\n"
                f"参与用户: {users[0] if users else 0}")

    # ============ API 接口 ============

    def api_stats(self, data):
        return {
            'success': True,
            'plugin': self.name,
            'total_messages': self.metric_total(),
            'today_messages': self.metric_today(),
            'unique_users': self.metric_users()
        }

    def api_top(self, data):
        rows = self.database.fetch_all(
            'SELECT sender_uid, COUNT(*) as cnt FROM message_log '
            'GROUP BY sender_uid ORDER BY cnt DESC LIMIT 10')
        return {
            'success': True,
            'top_users': [{'uid': r[0], 'count': r[1]} for r in rows]
        }

    # ============ 指标收集 ============

    def metric_total(self):
        row = self.database.fetch_one('SELECT COUNT(*) FROM message_log')
        return row[0] if row else 0

    def metric_today(self):
        row = self.database.fetch_one(
            "SELECT COUNT(*) FROM message_log WHERE created_at >= ?",
            ((datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),))
        return row[0] if row else 0

    def metric_users(self):
        row = self.database.fetch_one('SELECT COUNT(DISTINCT sender_uid) FROM message_log')
        return row[0] if row else 0
