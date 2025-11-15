import json
import time
import logging
import requests
import threading
from typing import Dict, List, Any, Callable, Optional, Union
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import sqlite3
import hashlib
import os

class PluginLogger:
    """插件专用日志记录器"""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.logger = logging.getLogger(f"plugin.{plugin_name}")
    
    def info(self, message: str):
        """信息日志"""
        self.logger.info(f"[{self.plugin_name}] {message}")
    
    def error(self, message: str):
        """错误日志"""
        self.logger.error(f"[{self.plugin_name}] {message}")
    
    def warning(self, message: str):
        """警告日志"""
        self.logger.warning(f"[{self.plugin_name}] {message}")
    
    def debug(self, message: str):
        """调试日志"""
        self.logger.debug(f"[{self.plugin_name}] {message}")

class PluginConfig:
    """插件配置管理器"""
    
    def __init__(self, plugin_name: str, config_manager=None):
        self.plugin_name = plugin_name
        self.config_manager = config_manager
        self.config_file = f"plugins/{plugin_name}/config.json"
        self._config = {}
        self.load_config()
    
    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
        except Exception as e:
            logging.error(f"加载插件 {self.plugin_name} 配置失败: {str(e)}")
    
    def save_config(self):
        """保存配置"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error(f"保存插件 {self.plugin_name} 配置失败: {str(e)}")
            return False
    
    def get(self, key: str, default=None):
        """获取配置值"""
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self._config[key] = value
        return self.save_config()
    
    def delete(self, key: str):
        """删除配置项"""
        if key in self._config:
            del self._config[key]
            return self.save_config()
        return True

class PluginDatabase:
    """插件数据库管理器"""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.db_file = f"plugins/{plugin_name}/{plugin_name}.db"
        self._ensure_db_file()
    
    def _ensure_db_file(self):
        """确保数据库文件存在"""
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_file)
    
    def execute(self, sql: str, params: tuple = ()):
        """执行SQL语句"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor
        finally:
            conn.close()
    
    def fetch_all(self, sql: str, params: tuple = ()):
        """获取所有结果"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()
    
    def fetch_one(self, sql: str, params: tuple = ()):
        """获取单个结果"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            conn.close()
    
    def create_table(self, table_name: str, columns: Dict[str, str]):
        """创建表"""
        columns_sql = ', '.join([f'{name} {type}' for name, type in columns.items()])
        sql = f'CREATE TABLE IF NOT EXISTS {table_name} ({columns_sql})'
        self.execute(sql)

class PluginCache:
    """插件缓存管理器"""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.cache_file = f"plugins/{plugin_name}/cache.json"
        self._cache = {}
        self._load_cache()
    
    def _load_cache(self):
        """加载缓存"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
        except:
            self._cache = {}
    
    def _save_cache(self):
        """保存缓存"""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except:
            pass
    
    def get(self, key: str, default=None):
        """获取缓存值"""
        item = self._cache.get(key)
        if item and 'expires' in item and item['expires'] < time.time():
            del self._cache[key]
            self._save_cache()
            return default
        return item.get('value', default) if item else default
    
    def set(self, key: str, value: Any, ttl: int = 0):
        """设置缓存值"""
        item = {'value': value}
        if ttl > 0:
            item['expires'] = time.time() + ttl
        self._cache[key] = item
        self._save_cache()
    
    def delete(self, key: str):
        """删除缓存项"""
        if key in self._cache:
            del self._cache[key]
            self._save_cache()
    
    def clear(self):
        """清空缓存"""
        self._cache = {}
        self._save_cache()

class PluginHTTPClient:
    """插件HTTP客户端"""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'BilibiliBot-Plugin-{plugin_name}/1.0.0'
        })
    
    def get(self, url: str, **kwargs):
        """GET请求"""
        return self._request('GET', url, **kwargs)
    
    def post(self, url: str, **kwargs):
        """POST请求"""
        return self._request('POST', url, **kwargs)
    
    def _request(self, method: str, url: str, **kwargs):
        """发送请求"""
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logging.error(f"插件 {self.plugin_name} HTTP请求失败: {str(e)}")
            raise

class PluginScheduler:
    """插件任务调度器"""
    
    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        self.timers = []
    
    def schedule_interval(self, interval: int, func: Callable, *args, **kwargs):
        """定时执行任务"""
        def wrapper():
            while True:
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logging.error(f"插件 {self.plugin_name} 定时任务执行失败: {str(e)}")
                time.sleep(interval)
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        self.timers.append(thread)
        return thread
    
    def schedule_once(self, delay: int, func: Callable, *args, **kwargs):
        """延迟执行任务"""
        def wrapper():
            time.sleep(delay)
            try:
                func(*args, **kwargs)
            except Exception as e:
                logging.error(f"插件 {self.plugin_name} 延迟任务执行失败: {str(e)}")
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        self.timers.append(thread)
        return thread
    
    def stop_all(self):
        """停止所有任务"""
        for timer in self.timers:
            if timer.is_alive():
                # 无法直接停止线程，但可以设置标志位
                pass

class PluginUtils:
    """插件工具类"""
    
    @staticmethod
    def format_time(timestamp: float = None) -> str:
        """格式化时间"""
        if timestamp is None:
            timestamp = time.time()
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    
    @staticmethod
    def md5(text: str) -> str:
        """计算MD5"""
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def safe_json_loads(text: str, default=None):
        """安全JSON解析"""
        try:
            return json.loads(text)
        except:
            return default
    
    @staticmethod
    def chunk_list(lst: List, size: int) -> List[List]:
        """分割列表"""
        return [lst[i:i + size] for i in range(0, len(lst), size)]
    
    @staticmethod
    def format_file_size(size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

# 增强的插件基类 - 统一所有基础功能
class PluginBase(ABC):
    """插件基类 - 提供完整的开发工具"""
    
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        self.bot_manager = bot_manager
        self.config_manager = config_manager
        self.plugin_config = plugin_config or {}
        self.name = self.plugin_config.get('name', self.__class__.__name__)
        self.version = self.plugin_config.get('version', '1.0.0')
        
        # 初始化工具类
        self.logger = PluginLogger(self.name)
        self.config = PluginConfig(self.name, config_manager)
        self.database = PluginDatabase(self.name)
        self.cache = PluginCache(self.name)
        self.http = PluginHTTPClient(self.name)
        self.scheduler = PluginScheduler(self.name)
        self.utils = PluginUtils()
        
        # 初始化各种处理器
        self.message_handlers = []
        self.command_handlers = {}
        self.event_handlers = {}
        self.api_routes = {}
        self.metrics = {}
        
        self.logger.info(f"插件工具类初始化完成")
    
    @abstractmethod
    def on_load(self):
        """插件加载时调用"""
        pass
    
    @abstractmethod
    def on_unload(self):
        """插件卸载时调用"""
        pass
    
    # 消息处理相关方法
    def register_message_handler(self, handler: Callable):
        """注册消息处理器"""
        self.message_handlers.append(handler)
        self.logger.info(f"注册消息处理器: {handler.__name__}")
    
    def register_command(self, command: str, handler: Callable, description: str = ""):
        """注册命令处理器"""
        self.command_handlers[command] = {
            'handler': handler,
            'description': description
        }
        self.logger.info(f"注册命令: {command} - {description}")
    
    def process_message(self, message_data: Dict[str, Any]) -> Optional[str]:
        """处理消息"""
        content = message_data.get('content', '')
        
        # 检查命令
        if content.startswith('!'):
            parts = content[1:].split(' ', 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ''
            
            if command in self.command_handlers:
                try:
                    return self.command_handlers[command]['handler'](message_data, args)
                except Exception as e:
                    self.logger.error(f"命令处理失败: {command} - {str(e)}")
                    return f"命令执行失败: {str(e)}"
        
        # 检查消息处理器
        for handler in self.message_handlers:
            try:
                result = handler(message_data)
                if result:
                    return result
            except Exception as e:
                self.logger.error(f"消息处理失败: {handler.__name__} - {str(e)}")
        
        return None
    
    # 事件处理相关方法
    def register_event_handler(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        self.logger.info(f"注册事件处理器: {event_type} - {handler.__name__}")
    
    def emit_event(self, event_type: str, data: Any = None):
        """触发事件"""
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    self.logger.error(f"事件处理失败: {event_type} - {handler.__name__} - {str(e)}")
    
    # API相关方法
    def register_api_route(self, path: str, handler: Callable, methods: List[str] = None):
        """注册API路由"""
        if methods is None:
            methods = ['GET']
        self.api_routes[path] = {
            'handler': handler,
            'methods': methods
        }
        self.logger.info(f"注册API路由: {path} - {methods}")
    
    def handle_api_request(self, path: str, method: str, data: Any = None) -> Any:
        """处理API请求"""
        if path in self.api_routes:
            route = self.api_routes[path]
            if method in route['methods']:
                try:
                    return route['handler'](data)
                except Exception as e:
                    self.logger.error(f"API处理失败: {path} - {str(e)}")
                    return {'error': str(e)}
        return None
    
    # 数据分析相关方法
    def register_metric(self, name: str, collector: Callable):
        """注册指标收集器"""
        self.metrics[name] = collector
        self.logger.info(f"注册指标: {name}")
    
    def collect_metrics(self) -> Dict[str, Any]:
        """收集所有指标"""
        results = {}
        for name, collector in self.metrics.items():
            try:
                results[name] = collector()
            except Exception as e:
                self.logger.error(f"指标收集失败: {name} - {str(e)}")
                results[name] = None
        return results
    
    def create_dashboard_data(self) -> Dict[str, Any]:
        """创建仪表板数据"""
        return {
            'metrics': self.collect_metrics(),
            'timestamp': self.utils.format_time(),
            'plugin': self.name
        }
    
    # 机器人交互方法
    def get_bot_accounts(self):
        """获取所有机器人账号"""
        if self.bot_manager and hasattr(self.bot_manager, 'bots'):
            return self.bot_manager.bots
        return []
    
    def send_message(self, receiver_id: int, message: str, account_index: int = 0):
        """发送消息"""
        accounts = self.get_bot_accounts()
        if account_index < len(accounts):
            return accounts[account_index].send_message(receiver_id, message)
        return False
    
    def get_user_info(self, user_id: int, account_index: int = 0):
        """获取用户信息"""
        accounts = self.get_bot_accounts()
        if account_index < len(accounts):
            return accounts[account_index].get_userName(user_id)
        return None

# 为了向后兼容，保留原有的专用插件基类
class MessagePlugin(PluginBase):
    """消息处理插件基类 - 向后兼容"""
    pass

class EventPlugin(PluginBase):
    """事件处理插件基类 - 向后兼容"""
    pass

class APIPlugin(PluginBase):
    """API插件基类 - 向后兼容"""
    pass

class AnalysisPlugin(PluginBase):
    """数据分析插件基类 - 向后兼容"""
    pass

# 插件开发辅助工具
class PluginDeveloper:
    """插件开发辅助工具类"""

    @staticmethod
    def create_plugin_template(plugin_name: str, plugin_type: str = "base") -> str:
        """创建插件模板代码"""
        base_template = f'''
import plugin_dev

class Plugin(plugin_dev.PluginBase):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
    
    def on_load(self):
        """插件加载时调用"""
        self.logger.info("插件 {{self.name}} 加载成功")
    
    def on_unload(self):
        """插件卸载时调用"""
        self.logger.info("插件 {{self.name}} 卸载成功")
'''
        
        templates = {
            "base": base_template,
            "message": f'''
import plugin_dev

class Plugin(plugin_dev.PluginBase):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        
        # 注册消息处理器
        self.register_message_handler(self.handle_test_message)
        self.register_command("help", self.handle_help_command, "显示帮助信息")
    
    def on_load(self):
        """插件加载时调用"""
        self.logger.info("消息插件 {{self.name}} 加载成功")
    
    def on_unload(self):
        """插件卸载时调用"""
        self.logger.info("消息插件 {{self.name}} 卸载成功")
    
    def handle_test_message(self, message_data):
        """处理测试消息"""
        content = message_data.get('content', '')
        if '测试' in content:
            return '这是一个测试回复'
        return None
    
    def handle_help_command(self, message_data, args):
        """处理帮助命令"""
        return "这是帮助信息：使用 !help 查看命令"
''',
            "event": f'''
import plugin_dev

class Plugin(plugin_dev.PluginBase):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        
        # 注册事件处理器
        self.register_event_handler('bot_start', self.on_bot_start)
        self.register_event_handler('bot_stop', self.on_bot_stop)
    
    def on_load(self):
        """插件加载时调用"""
        self.logger.info("事件插件 {{self.name}} 加载成功")
    
    def on_unload(self):
        """插件卸载时调用"""
        self.logger.info("事件插件 {{self.name}} 卸载成功")
    
    def on_bot_start(self, data):
        """机器人启动事件"""
        self.logger.info("机器人启动了！")
    
    def on_bot_stop(self, data):
        """机器人停止事件"""
        self.logger.info("机器人停止了！")
''',
            "api": f'''
import plugin_dev

class Plugin(plugin_dev.PluginBase):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        
        # 注册API路由
        self.register_api_route('/{plugin_name}/info', self.get_plugin_info)
        self.register_api_route('/{plugin_name}/stats', self.get_plugin_stats, methods=['GET', 'POST'])
    
    def on_load(self):
        """插件加载时调用"""
        self.logger.info("API插件 {{self.name}} 加载成功")
    
    def on_unload(self):
        """插件卸载时调用"""
        self.logger.info("API插件 {{self.name}} 卸载成功")
    
    def get_plugin_info(self, data):
        """获取插件信息API"""
        return {{
            'name': self.name,
            'version': self.version,
            'status': 'running'
        }}
    
    def get_plugin_stats(self, data):
        """获取插件统计API"""
        return {{
            'requests_handled': 0,
            'uptime': '0s'
        }}
''',
            "analysis": f'''
import plugin_dev
import time

class Plugin(plugin_dev.PluginBase):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        self.start_time = time.time()
        
        # 注册指标收集器
        self.register_metric('uptime', self.get_uptime)
        self.register_metric('message_count', self.get_message_count)
    
    def on_load(self):
        """插件加载时调用"""
        self.logger.info("数据分析插件 {{self.name}} 加载成功")
    
    def on_unload(self):
        """插件卸载时调用"""
        self.logger.info("数据分析插件 {{self.name}} 卸载成功")
    
    def get_uptime(self):
        """获取运行时间指标"""
        return time.time() - self.start_time
    
    def get_message_count(self):
        """获取消息计数指标"""
        return 0
'''
        }
        
        return templates.get(plugin_type, base_template).strip()
    
    @staticmethod
    def validate_plugin_structure(plugin_path: str) -> Dict[str, Any]:
        """验证插件结构"""
        results = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        # 检查必要文件
        required_files = ['package.json', 'main.py']
        for file in required_files:
            if not os.path.exists(os.path.join(plugin_path, file)):
                results['valid'] = False
                results['errors'].append(f"缺少必要文件: {file}")
        
        # 检查package.json
        try:
            with open(os.path.join(plugin_path, 'package.json'), 'r', encoding='utf-8') as f:
                package = json.load(f)
            
            required_fields = ['name', 'version', 'description', 'author']
            for field in required_fields:
                if field not in package:
                    results['valid'] = False
                    results['errors'].append(f"package.json 缺少必要字段: {field}")
            
            # 建议字段
            suggested_fields = ['repository', 'license', 'keywords', 'dependencies']
            for field in suggested_fields:
                if field not in package:
                    results['suggestions'].append(f"建议添加字段: {field}")
                    
        except Exception as e:
            results['valid'] = False
            results['errors'].append(f"package.json 解析错误: {str(e)}")
        
        # 检查main.py
        try:
            with open(os.path.join(plugin_path, 'main.py'), 'r', encoding='utf-8') as f:
                content = f.read()
            
            if 'class Plugin' not in content:
                results['valid'] = False
                results['errors'].append("main.py 中没有找到 Plugin 类")
            
            if 'on_load' not in content:
                results['valid'] = False
                results['errors'].append("Plugin 类缺少 on_load 方法")
            
            if 'on_unload' not in content:
                results['valid'] = False
                results['errors'].append("Plugin 类缺少 on_unload 方法")
                
        except Exception as e:
            results['valid'] = False
            results['errors'].append(f"main.py 读取错误: {str(e)}")
        
        return results
    
    @staticmethod
    def generate_plugin_docs(plugin_path: str) -> str:
        """生成插件文档"""
        try:
            with open(os.path.join(plugin_path, 'package.json'), 'r', encoding='utf-8') as f:
                package = json.load(f)
            
            docs = f"""# {package.get('name', 'Unknown Plugin')}

版本: {package.get('version', '1.0.0')}

## 描述

{package.get('description', '暂无描述')}

## 作者

{package.get('author', '未知')}

## 功能特性

- TODO: 添加功能特性

## 安装

1. 将插件文件夹复制到 `plugins` 目录
2. 在管理面板中启用插件

## 配置

插件配置位于 `plugins/{package.get('name')}/config.json`

## API接口

- TODO: 描述API接口

## 事件

- TODO: 描述事件

## 命令

- TODO: 描述命令

## 开发说明

这是一个 {package.get('type', 'base')} 类型的插件。
"""
            return docs
            
        except Exception as e:
            return f"生成文档失败: {str(e)}"
    
    @staticmethod
    def create_plugin_test(plugin_name: str, test_type: str = "basic") -> str:
        """创建插件测试代码"""
        templates = {
            "basic": f'''
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from plugins.{plugin_name}.main import Plugin

def test_plugin_loading():
    # 测试插件加载
    plugin = Plugin()
    plugin.on_load()
    assert plugin.name == "{plugin_name}"
    plugin.on_unload()

def test_plugin_config():
    # 测试插件配置
    plugin = Plugin()
    assert hasattr(plugin, 'config')
    assert hasattr(plugin, 'logger')

if __name__ == "__main__":
    test_plugin_loading()
    test_plugin_config()
    print("所有测试通过！")
""",
            "message": f"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from plugins.{plugin_name}.main import Plugin

def test_message_handling():
    #测试消息处理
    plugin = Plugin()
    plugin.on_load()
    
    # 测试消息处理
    test_message = {{
        'content': '测试消息',
        'sender_uid': 123456,
        'timestamp': 1234567890
    }}
    
    result = plugin.process_message(test_message)
    print(f"消息处理结果: {{result}}")
    
    plugin.on_unload()

if __name__ == "__main__":
    test_message_handling()
'''
        }
        
        return templates.get(test_type, templates["basic"])