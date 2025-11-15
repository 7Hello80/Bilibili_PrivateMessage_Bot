import os
import json
import importlib.util
import sys
import logging
from typing import Dict, List, Any, Optional
import requests
import threading
from pathlib import Path

class Plugin:
    def __init__(self, name: str, path: str, metadata: Dict[str, Any]):
        self.name = name
        self.path = path
        self.metadata = metadata
        self.enabled = metadata.get('enabled', True)
        self.module = None
        self.instance = None
        self.load_order = metadata.get('load_order', 0)
    
    def load(self, bot_manager=None, config_manager=None):
        """加载插件"""
        try:
            # 确保插件目录在 Python 路径中
            if self.path not in sys.path:
                sys.path.insert(0, self.path)
            
            spec = importlib.util.spec_from_file_location(
                f"plugins.{self.name}", 
                os.path.join(self.path, "main.py")
            )
            
            if spec is None:
                logging.error(f"无法创建插件 {self.name} 的模块规范")
                return False
                
            self.module = importlib.util.module_from_spec(spec)
            
            # 确保模块在 sys.modules 中注册
            sys.modules[f"plugins.{self.name}"] = self.module
            
            # 执行模块代码
            spec.loader.exec_module(self.module)
            
            # 初始化插件实例
            if hasattr(self.module, 'Plugin'):
                # 获取插件类
                plugin_class = getattr(self.module, 'Plugin')
                
                # 创建插件实例
                self.instance = plugin_class(
                    bot_manager=bot_manager,
                    config_manager=config_manager,
                    plugin_config=self.metadata
                )
                
                # 调用插件的初始化方法
                if hasattr(self.instance, 'on_load'):
                    try:
                        self.instance.on_load()
                        logging.info(f"插件 {self.name} 加载成功并初始化")
                    except Exception as e:
                        logging.error(f"插件 {self.name} 初始化失败: {str(e)}")
                        return False
                        
                return True
            else:
                logging.error(f"插件 {self.name} 没有找到 Plugin 类")
                return False
                
        except Exception as e:
            logging.error(f"加载插件 {self.name} 失败: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return False
    
    def unload(self):
        """卸载插件"""
        try:
            if self.instance and hasattr(self.instance, 'on_unload'):
                self.instance.on_unload()
            
            # 从sys.modules中移除
            module_name = f"plugins.{self.name}"
            if module_name in sys.modules:
                del sys.modules[module_name]
                
            self.module = None
            self.instance = None
            logging.info(f"插件 {self.name} 卸载成功")
            return True
        except Exception as e:
            logging.error(f"卸载插件 {self.name} 失败: {str(e)}")
            return False
    
    def reload(self):
        """重新加载插件"""
        self.unload()
        return self.load()

class PluginLoader:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self.plugins: Dict[str, Plugin] = {}
        self.bot_manager = None
        self.config_manager = None
        
        # 创建插件目录
        os.makedirs(plugins_dir, exist_ok=True)
    
    def set_dependencies(self, bot_manager, config_manager):
        """设置依赖项"""
        self.bot_manager = bot_manager
        self.config_manager = config_manager
    
    def discover_plugins(self) -> List[str]:
        """发现所有插件"""
        plugins = []
        if not os.path.exists(self.plugins_dir):
            return plugins
            
        for item in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, item)
            if os.path.isdir(plugin_path):
                package_json = os.path.join(plugin_path, "package.json")
                main_py = os.path.join(plugin_path, "main.py")
                
                if os.path.exists(package_json) and os.path.exists(main_py):
                    plugins.append(item)
        
        return plugins
    
    def load_plugin(self, plugin_name: str) -> bool:
        """加载单个插件"""
        try:
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            package_json_path = os.path.join(plugin_path, "package.json")
            
            with open(package_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            plugin = Plugin(plugin_name, plugin_path, metadata)
            
            # 只有启用的插件才加载
            if plugin.enabled:
                success = plugin.load(self.bot_manager, self.config_manager)
                if success:
                    self.plugins[plugin_name] = plugin
                    return True
            else:
                self.plugins[plugin_name] = plugin
                return True
                
            return False
            
        except Exception as e:
            logging.error(f"加载插件 {plugin_name} 时出错: {str(e)}")
            return False
    
    def load_all_plugins(self) -> bool:
        """加载所有插件"""
        plugin_names = self.discover_plugins()
        
        # 按加载顺序排序
        plugins_with_order = []
        for name in plugin_names:
            try:
                plugin_path = os.path.join(self.plugins_dir, name)
                package_json_path = os.path.join(plugin_path, "package.json")
                
                with open(package_json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                load_order = metadata.get('load_order', 0)
                plugins_with_order.append((name, load_order))
            except:
                plugins_with_order.append((name, 0))
        
        # 按加载顺序排序
        plugins_with_order.sort(key=lambda x: x[1])
        
        success_count = 0
        for name, _ in plugins_with_order:
            if self.load_plugin(name):
                success_count += 1
        
        logging.info(f"插件加载完成: {success_count}/{len(plugin_names)} 个插件加载成功")
        return success_count > 0
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件"""
        if plugin_name in self.plugins:
            plugin = self.plugins[plugin_name]
            success = plugin.unload()
            if success:
                del self.plugins[plugin_name]
            return success
        return False
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """重新加载插件"""
        if plugin_name in self.plugins:
            return self.plugins[plugin_name].reload()
        else:
            return self.load_plugin(plugin_name)
    
    def get_plugin(self, plugin_name: str) -> Optional[Plugin]:
        """获取插件实例"""
        return self.plugins.get(plugin_name)
    
    def get_all_plugins(self) -> List[Plugin]:
        """获取所有插件"""
        return list(self.plugins.values())
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """启用插件"""
        try:
            # 首先确保插件配置文件中启用状态正确
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            package_json_path = os.path.join(plugin_path, "package.json")
            
            if os.path.exists(package_json_path):
                with open(package_json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                metadata['enabled'] = True
                
                with open(package_json_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=4, ensure_ascii=False)
            
            # 如果插件已经在内存中，更新状态
            if plugin_name in self.plugins:
                plugin = self.plugins[plugin_name]
                plugin.enabled = True
                plugin.metadata['enabled'] = True
                
                # 如果插件未加载，加载它
                if not plugin.instance:
                    return plugin.load(self.bot_manager, self.config_manager)
                return True
            else:
                # 如果插件不在内存中，加载它
                return self.load_plugin(plugin_name)
                
        except Exception as e:
            logging.error(f"启用插件 {plugin_name} 失败: {str(e)}")
            return False
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """禁用插件"""
        try:
            if plugin_name in self.plugins:
                plugin = self.plugins[plugin_name]
                
                # 如果插件已加载，先卸载
                if plugin.instance:
                    success = plugin.unload()
                    if not success:
                        logging.error(f"卸载插件 {plugin_name} 失败")
                        return False
                
                # 更新状态
                plugin.enabled = False
                plugin.metadata['enabled'] = False
                
                # 保存配置
                return self.save_plugin_metadata(plugin)
            else:
                # 如果插件不在内存中，直接从文件系统更新
                return self._disable_plugin_from_filesystem(plugin_name)
                
        except Exception as e:
            logging.error(f"禁用插件 {plugin_name} 失败: {str(e)}")
            return False
    
    def _disable_plugin_from_filesystem(self, plugin_name: str) -> bool:
        """从文件系统禁用插件"""
        try:
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            package_json_path = os.path.join(plugin_path, "package.json")
            
            if not os.path.exists(package_json_path):
                logging.error(f"插件 {plugin_name} 的 package.json 不存在")
                return False
            
            # 读取当前配置
            with open(package_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # 更新启用状态
            metadata['enabled'] = False
            
            # 保存配置
            with open(package_json_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            
            logging.info(f"已从文件系统禁用插件: {plugin_name}")
            return True
            
        except Exception as e:
            logging.error(f"从文件系统禁用插件 {plugin_name} 失败: {str(e)}")
            return False
    
    def save_plugin_metadata(self, plugin: Plugin) -> bool:
        """保存插件元数据"""
        try:
            package_json_path = os.path.join(plugin.path, "package.json")
            with open(package_json_path, 'w', encoding='utf-8') as f:
                json.dump(plugin.metadata, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error(f"保存插件 {plugin.name} 元数据失败: {str(e)}")
            return False
    
    def call_plugin_method(self, plugin_name: str, method_name: str, *args, **kwargs):
        """调用插件方法"""
        plugin = self.get_plugin(plugin_name)
        if plugin and plugin.instance:
            if hasattr(plugin.instance, method_name):
                method = getattr(plugin.instance, method_name)
                return method(*args, **kwargs)
        return None

# 全局插件加载器实例
plugin_loader = PluginLoader()