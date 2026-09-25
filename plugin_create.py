import os
import re
import json
import shutil
from typing import Dict, Any

PLUGIN_NAME_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


class PluginCreator:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir

    def create_plugin(self, plugin_name: str, plugin_type: str = "base",
                     author: str = "匿名", description: str = "",
                     version: str = "1.0.0", template_content: str = None) -> bool:
        """创建新插件(template_content 非空时直接作为 main.py 内容)"""
        try:
            # 插件名净化(防路径穿越)
            plugin_name = str(plugin_name or '').strip()
            if not PLUGIN_NAME_RE.match(plugin_name):
                print(f"插件名不合法: {plugin_name}")
                return False

            plugin_dir = os.path.join(self.plugins_dir, f'bilibot_plugins_{plugin_name}')

            # 检查插件是否已存在
            if os.path.exists(plugin_dir):
                print(f"插件 {plugin_name} 已存在")
                return False

            # 创建插件目录
            os.makedirs(plugin_dir, exist_ok=True)

            # 创建package.json
            package_data = {
                "name": plugin_name,
                "version": version,
                "description": description or f"{plugin_name} 插件",
                "author": author,
                "type": plugin_type,
                "repository": "",
                "license": "MIT",
                "enabled": True,
                "load_order": 0,
                "dependencies": [],
                "bypass_follow_check": False
            }

            with open(os.path.join(plugin_dir, "package.json"), 'w', encoding='utf-8') as f:
                json.dump(package_data, f, indent=4, ensure_ascii=False)

            # 创建main.py(优先使用自定义模板内容)
            if template_content:
                content = template_content.strip()
            else:
                from plugin_dev import PluginDeveloper
                content = PluginDeveloper.create_plugin_template(plugin_name, plugin_type).strip()

            with open(os.path.join(plugin_dir, "main.py"), 'w', encoding='utf-8') as f:
                f.write(content)

            # 创建README.md
            readme_content = f"""# {plugin_name}

{description}

## 功能说明

这是一个 {plugin_type} 类型的插件。

## 安装

1. 将本插件复制到 `plugins` 目录
2. 在管理面板中启用插件

## 配置

插件配置位于 `plugins/bilibot_plugins_{plugin_name}/config.json`

## 使用方法

插件加载后自动生效。
"""
            with open(os.path.join(plugin_dir, "README.md"), 'w', encoding='utf-8') as f:
                f.write(readme_content)

            print(f"插件 {plugin_name} 创建成功")
            print(f"目录: {plugin_dir}")
            return True

        except Exception as e:
            print(f"创建插件失败: {str(e)}")
            return False

    def create_from_template(self, template_name: str, plugin_name: str, **kwargs) -> bool:
        """从模板创建插件(模板内容真正写入 main.py)"""
        templates = self.get_templates()

        if template_name not in templates:
            print(f"模板 {template_name} 不存在")
            return False

        template = templates[template_name]
        return self.create_plugin(
            plugin_name=plugin_name,
            plugin_type=template["type"],
            description=template["description"],
            template_content=template["template"],
            **kwargs
        )

    def get_templates(self) -> Dict[str, Dict[str, str]]:
        """内置模板列表(展示新能力: 缓存冷却/reply方法/bypass_follow_check/数据库/指标)"""
        return {
            "keyword_reply": {
                "type": "message",
                "description": "关键词自动回复插件(带冷却防刷)",
                "template": '''
import plugin_dev
import time

class Plugin(plugin_dev.MessagePlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"

        # 注册消息处理器
        self.register_message_handler(self.handle_keywords)

    def on_load(self):
        self.logger.info(f"关键词回复插件 {self.name} 加载成功")

    def on_unload(self):
        self.logger.info(f"关键词回复插件 {self.name} 卸载成功")

    def handle_keywords(self, message_data):
        content = message_data.get('content', '')
        sender_uid = str(message_data.get('sender_uid', ''))

        # 冷却检查: 同一用户 60 秒内只回复一次(演示 PluginCache TTL)
        if self.cache.get(f"cooldown_{sender_uid}"):
            return None

        keywords = {
            '你好': '你好！欢迎使用B站私信机器人！',
            '时间': f'当前时间: {self.get_current_time()}'
        }

        for keyword, reply in keywords.items():
            if keyword in content:
                self.cache.set(f"cooldown_{sender_uid}", 1, ttl=60)
                return reply

        return None

    def get_current_time(self):
        return time.strftime('%Y-%m-%d %H:%M:%S')
'''
            },
            "data_analysis": {
                "type": "analysis",
                "description": "数据统计与分析插件(数据库+指标)",
                "template": '''
import plugin_dev
import time
from datetime import datetime

class Plugin(plugin_dev.AnalysisPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        self.start_time = time.time()

        # 建表(演示 PluginDatabase)
        self.database.create_table('message_log', {
            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
            'sender_uid': 'TEXT',
            'content': 'TEXT',
            'created_at': 'TEXT'
        })

        # 注册事件处理器
        self.register_event_handler('message_received', self.on_message_received)

        # 注册命令
        self.register_command('stats', self.cmd_stats, '查看消息统计')

        # 注册指标(面板指标页可查看)
        self.register_metric('total_messages', self.metric_total)
        self.register_metric('uptime', self.metric_uptime)

    def on_load(self):
        self.logger.info(f"数据分析插件 {self.name} 加载成功")

    def on_unload(self):
        self.logger.info(f"数据分析插件 {self.name} 卸载成功")

    def on_message_received(self, message_data):
        sender_uid = str(message_data.get('sender_uid', ''))
        content = message_data.get('content', '')
        self.database.execute(
            'INSERT INTO message_log (sender_uid, content, created_at) VALUES (?, ?, ?)',
            (sender_uid, content, self.utils.format_time()))

    def cmd_stats(self, message_data, args):
        total = self.database.fetch_one('SELECT COUNT(*) FROM message_log')
        users = self.database.fetch_one('SELECT COUNT(DISTINCT sender_uid) FROM message_log')
        return (f"📊 消息统计\\n"
                f"总消息数: {total[0] if total else 0}\\n"
                f"参与用户: {users[0] if users else 0}")

    def metric_total(self):
        total = self.database.fetch_one('SELECT COUNT(*) FROM message_log')
        return total[0] if total else 0

    def metric_uptime(self):
        return int(time.time() - self.start_time)

    def get_statistics(self):
        return {
            'total_messages': self.metric_total(),
            'uptime': self.metric_uptime(),
            'start_time': datetime.fromtimestamp(self.start_time).isoformat()
        }
'''
            }
        }

# 全局插件创建器实例
plugin_creator = PluginCreator()