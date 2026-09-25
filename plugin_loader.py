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
        self.load_error = None  # 加载失败原因(供面板展示)
        # 保存依赖, reload 时复用
        self._bot_manager = None
        self._config_manager = None

    def load(self, bot_manager=None, config_manager=None):
        """加载插件"""
        try:
            # 保存依赖供 reload 使用
            if bot_manager is not None:
                self._bot_manager = bot_manager
            if config_manager is not None:
                self._config_manager = config_manager
            self.load_error = None

            # 确保插件目录在 Python 路径中
            if self.path not in sys.path:
                sys.path.insert(0, self.path)
            
            spec = importlib.util.spec_from_file_location(
                f"plugins.{self.name}", 
                os.path.join(self.path, "main.py")
            )
            
            if spec is None:
                msg = f"无法创建插件 {self.name} 的模块规范"
                self.load_error = msg
                logging.error(msg)
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
                        msg = f"插件 {self.name} 初始化失败: {str(e)}"
                        self.load_error = msg
                        logging.error(msg)
                        # 实例化失败时清理状态
                        self.instance = None
                        self._remove_module()
                        return False

                return True
            else:
                msg = f"插件 {self.name} 没有找到 Plugin 类"
                self.load_error = msg
                logging.error(msg)
                self._remove_module()
                return False

        except Exception as e:
            msg = f"加载插件 {self.name} 失败: {str(e)}"
            self.load_error = msg
            logging.error(msg)
            import traceback
            logging.error(traceback.format_exc())
            self._remove_module()
            return False

    def _remove_module(self):
        """从 sys.modules 移除插件模块(加载失败清理)"""
        module_name = f"plugins.{self.name}"
        if module_name in sys.modules:
            try:
                del sys.modules[module_name]
            except KeyError:
                pass
        self.module = None
        self.instance = None
    
    def unload(self):
        """卸载插件"""
        try:
            if self.instance and hasattr(self.instance, 'on_unload'):
                try:
                    self.instance.on_unload()
                except Exception as e:
                    logging.error(f"插件 {self.name} on_unload 执行失败: {str(e)}")

            # 兜底清理定时任务线程(即使插件忘了 stop)
            if self.instance and hasattr(self.instance, 'scheduler'):
                try:
                    self.instance.scheduler.stop_all()
                except Exception as e:
                    logging.error(f"插件 {self.name} 定时器清理失败: {str(e)}")

            # 从sys.modules中移除
            module_name = f"plugins.{self.name}"
            if module_name in sys.modules:
                del sys.modules[module_name]

            self.module = None
            self.instance = None
            self.load_error = None
            logging.info(f"插件 {self.name} 卸载成功")
            return True
        except Exception as e:
            logging.error(f"卸载插件 {self.name} 失败: {str(e)}")
            return False

    def reload(self):
        """重新加载插件(复用保存的依赖)"""
        self.unload()
        return self.load(self._bot_manager, self._config_manager)

class PluginLoader:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self.plugins: Dict[str, Plugin] = {}
        self.bot_manager = None
        self.config_manager = None
        self.lock = threading.RLock()  # 保证 load/unload/reload/emit 线程安全

        # 创建插件目录
        os.makedirs(plugins_dir, exist_ok=True)

    def set_dependencies(self, bot_manager, config_manager):
        """设置依赖项"""
        with self.lock:
            self.bot_manager = bot_manager
            self.config_manager = config_manager

    def discover_plugins(self) -> List[str]:
        """发现所有插件"""
        plugins = []
        if not os.path.exists(self.plugins_dir):
            return plugins

        for item in sorted(os.listdir(self.plugins_dir)):
            plugin_path = os.path.join(self.plugins_dir, item)
            if os.path.isdir(plugin_path):
                package_json = os.path.join(plugin_path, "package.json")
                main_py = os.path.join(plugin_path, "main.py")

                if os.path.exists(package_json) and os.path.exists(main_py):
                    plugins.append(item)

        return plugins

    def check_dependencies(self, metadata: Dict[str, Any]):
        """校验插件依赖.
        - 若 plugins/<dep>/package.json 存在: 视为插件依赖, 要求该插件已加载
        - 否则视为 Python 模块依赖, 用 find_spec 探测
        返回 (是否满足, 原因)"""
        dependencies = metadata.get('dependencies', []) or []
        if not dependencies:
            return True, ""
        missing = []
        for dep in dependencies:
            if isinstance(dep, dict):
                dep = dep.get('name', '')
            dep = str(dep).strip()
            if not dep:
                continue
            dep_plugin_dir = os.path.join(self.plugins_dir, dep)
            if os.path.isdir(dep_plugin_dir) and os.path.exists(
                    os.path.join(dep_plugin_dir, "package.json")):
                # 插件依赖: 要求已加载
                target = self.plugins.get(dep)
                if target and target.instance is not None:
                    continue
                if target and not target.enabled:
                    missing.append(f"插件依赖 {dep} 未启用")
                else:
                    missing.append(f"插件依赖 {dep} 未加载")
            else:
                # Python 模块依赖
                if importlib.util.find_spec(dep) is None:
                    missing.append(f"Python 模块 {dep} 未安装")
        if missing:
            return False, "; ".join(missing)
        return True, ""

    def load_plugin(self, plugin_name: str) -> bool:
        """加载单个插件(依赖不满足时记录 load_error 并跳过加载)"""
        with self.lock:
            try:
                plugin_path = os.path.join(self.plugins_dir, plugin_name)
                package_json_path = os.path.join(plugin_path, "package.json")

                with open(package_json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # 已加载则跳过(幂等)
                existing = self.plugins.get(plugin_name)
                if existing and existing.instance is not None:
                    return True

                plugin = existing if existing else Plugin(plugin_name, plugin_path, metadata)
                if existing:
                    plugin.metadata = metadata
                    plugin.enabled = metadata.get('enabled', True)

                # 只有启用的插件才加载
                if plugin.enabled:
                    ok, reason = self.check_dependencies(metadata)
                    if not ok:
                        plugin.load_error = f"依赖不满足: {reason}"
                        self.plugins[plugin_name] = plugin
                        logging.error(f"插件 {plugin_name} 依赖不满足: {reason}")
                        return False
                    success = plugin.load(self.bot_manager, self.config_manager)
                    if success:
                        self.plugins[plugin_name] = plugin
                        return True
                    self.plugins[plugin_name] = plugin
                    return False
                else:
                    plugin.load_error = None
                    self.plugins[plugin_name] = plugin
                    return True

            except Exception as e:
                logging.error(f"加载插件 {plugin_name} 时出错: {str(e)}")
                return False

    def load_all_plugins(self) -> bool:
        """加载所有插件(失败的重试一轮, 解决依赖排序问题)"""
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
        failed = []
        for name, _ in plugins_with_order:
            if self.load_plugin(name):
                success_count += 1
            else:
                failed.append(name)

        # 依赖排序可能导致第一轮失败, 重试一轮
        for name in list(failed):
            if self.load_plugin(name):
                success_count += 1
                failed.remove(name)

        logging.info(f"插件加载完成: {success_count}/{len(plugin_names)} 个插件加载成功"
                     f"{('，失败: ' + ', '.join(failed)) if failed else ''}")
        return success_count > 0

    def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件"""
        with self.lock:
            if plugin_name in self.plugins:
                plugin = self.plugins[plugin_name]
                success = plugin.unload()
                if success:
                    del self.plugins[plugin_name]
                return success
            return False

    def reload_plugin(self, plugin_name: str) -> bool:
        """重新加载插件"""
        with self.lock:
            if plugin_name in self.plugins:
                plugin = self.plugins[plugin_name]
                # 重新读取磁盘上的元数据(enabled 状态可能已被面板修改)
                package_json_path = os.path.join(plugin.path, "package.json")
                try:
                    with open(package_json_path, 'r', encoding='utf-8') as f:
                        plugin.metadata = json.load(f)
                    plugin.enabled = plugin.metadata.get('enabled', True)
                except Exception:
                    pass
                if not plugin.enabled:
                    return self.unload_plugin(plugin_name)
                return plugin.reload()
            else:
                return self.load_plugin(plugin_name)

    def reload_all(self) -> bool:
        """重新加载全部插件"""
        with self.lock:
            ok = True
            for plugin in list(self.plugins.values()):
                if plugin.instance is not None:
                    if not plugin.reload():
                        ok = False
            # 同时尝试加载磁盘上有但未注册的插件
            for name in self.discover_plugins():
                if name not in self.plugins:
                    self.load_plugin(name)
            return ok

    def get_plugin(self, plugin_name: str) -> Optional[Plugin]:
        """获取插件实例"""
        return self.plugins.get(plugin_name)

    def get_all_plugins(self) -> List[Plugin]:
        """获取所有插件"""
        with self.lock:
            return list(self.plugins.values())

    def emit_event(self, event_type: str, data: Any = None):
        """向所有已加载插件广播事件(单个插件异常不阻断广播)"""
        with self.lock:
            for plugin in list(self.plugins.values()):
                if plugin.instance is None:
                    continue
                try:
                    plugin.instance.emit_event(event_type, data)
                except Exception as e:
                    logging.error(f"插件 {plugin.name} 处理事件 {event_type} 失败: {str(e)}")

    def get_help_text(self) -> str:
        """聚合所有已加载插件的命令帮助文本(供 !help)"""
        lines = []
        for plugin in self.get_all_plugins():
            if plugin.instance is None:
                continue
            try:
                commands = plugin.instance.get_commands_help()
            except Exception:
                commands = []
            if commands:
                lines.append(f"【{plugin.name}】")
                for cmd, desc in commands:
                    lines.append(f"  !{cmd}" + (f" - {desc}" if desc else ""))
        if not lines:
            return "暂无已注册的插件命令"
        return "插件命令列表:\n" + "\n".join(lines)

    def get_plugins_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有插件的运行状态(供 status 快照/面板展示)"""
        status = {}
        with self.lock:
            for plugin in self.plugins.values():
                status[plugin.name] = {
                    'enabled': plugin.enabled,
                    'loaded': plugin.instance is not None,
                    'version': plugin.metadata.get('version', '1.0.0'),
                    'error': plugin.load_error,
                    'api_routes': list(getattr(plugin.instance, 'api_routes', {}).keys())
                                  if plugin.instance else [],
                    'commands': [(cmd, info.get('description', ''))
                                 for cmd, info in
                                 getattr(plugin.instance, 'command_handlers', {}).items()]
                                if plugin.instance else []
                }
        return status

    def enable_plugin(self, plugin_name: str) -> bool:
        """启用插件(写入 package.json, 加载插件)"""
        with self.lock:
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
        with self.lock:
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