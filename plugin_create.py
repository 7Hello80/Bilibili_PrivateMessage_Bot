import os
import json
import shutil
from typing import Dict, Any

class PluginCreator:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
    
    def create_plugin(self, plugin_name: str, plugin_type: str = "base", 
                     author: str = "匿名", description: str = "", 
                     version: str = "1.0.0") -> bool:
        """创建新插件"""
        try:
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
                "dependencies": []
            }
            
            with open(os.path.join(plugin_dir, "package.json"), 'w', encoding='utf-8') as f:
                json.dump(package_data, f, indent=4, ensure_ascii=False)
            
            # 创建main.py
            from plugin_dev import PluginDeveloper
            template = PluginDeveloper.create_plugin_template(plugin_name, plugin_type)
            
            with open(os.path.join(plugin_dir, "main.py"), 'w', encoding='utf-8') as f:
                f.write(template.strip())
            
            # 创建README.md
            readme_content = f"""# {plugin_name}

{description}

## 功能说明

这是一个 {plugin_type} 类型的插件。

## 安装

1. 将本插件复制到 `plugins` 目录
2. 在管理面板中启用插件

## 配置

暂无特殊配置。

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
        """从模板创建插件"""
        templates = {
            "keyword_reply": {
                "type": "message",
                "description": "关键词自动回复插件",
                "template": """
import plugin_dev

class Plugin(plugin_dev.MessagePlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        
        # 注册关键词处理器
        self.register_message_handler(self.handle_keywords)
    
    def on_load(self):
        print(f"关键词回复插件 {self.name} 加载成功")
    
    def on_unload(self):
        print(f"关键词回复插件 {self.name} 卸载成功")
    
    def handle_keywords(self, message_data):
        content = message_data.get('content', '')
        sender_uid = message_data.get('sender_uid')
        
        # 这里可以添加你的关键词逻辑
        keywords = {
            '你好': '你好！欢迎使用B站私信机器人！',
            '帮助': '这是一个自动回复机器人，请输入关键词获取帮助。',
            '时间': f'当前时间: {self.get_current_time()}'
        }
        
        for keyword, reply in keywords.items():
            if keyword in content:
                return reply
        
        return None
    
    def get_current_time(self):
        import time
        return time.strftime('%Y-%m-%d %H:%M:%S')
"""
            },
            "data_analysis": {
                "type": "event",
                "description": "数据统计与分析插件",
                "template": """
import plugin_dev
import json
import time
from datetime import datetime

class Plugin(plugin_dev.EventPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        self.message_count = 0
        self.user_count = 0
        self.start_time = None
        
        # 注册事件处理器
        self.register_event_handler('message_received', self.on_message_received)
        self.register_event_handler('bot_start', self.on_bot_start)
    
    def on_load(self):
        print(f"数据分析插件 {self.name} 加载成功")
        self.load_statistics()
    
    def on_unload(self):
        print(f"数据分析插件 {self.name} 卸载成功")
        self.save_statistics()
    
    def on_bot_start(self, data):
        self.start_time = datetime.now()
    
    def on_message_received(self, message_data):
        self.message_count += 1
        self.save_statistics()
    
    def load_statistics(self):
        try:
            with open('plugin_statistics.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.message_count = data.get('message_count', 0)
                self.user_count = data.get('user_count', 0)
        except:
            pass
    
    def save_statistics(self):
        data = {
            'message_count': self.message_count,
            'user_count': self.user_count,
            'last_update': datetime.now().isoformat()
        }
        try:
            with open('plugin_statistics.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def get_statistics(self):
        uptime = (datetime.now() - self.start_time) if self.start_time else 0
        return {
            'message_count': self.message_count,
            'user_count': self.user_count,
            'uptime': str(uptime),
            'start_time': self.start_time.isoformat() if self.start_time else None
        }
"""
            }
        }
        
        if template_name not in templates:
            print(f"模板 {template_name} 不存在")
            return False
        
        template = templates[template_name]
        return self.create_plugin(
            plugin_name=plugin_name,
            plugin_type=template["type"],
            description=template["description"],
            **kwargs
        )

# 全局插件创建器实例
plugin_creator = PluginCreator()