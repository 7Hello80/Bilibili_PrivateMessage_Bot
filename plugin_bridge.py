# -*- coding: utf-8 -*-
"""
面板 <-> 机器人进程桥接模块
================================
1. 控制命令: 面板写 plugin_control.json(原子写), 机器人轮询执行(命令去重+过期)
2. 状态快照: 机器人写 plugin_status.json(原子写), 面板读取显示真实 loaded/error 状态
3. 插件API: 机器人在 127.0.0.1:9528 起极简HTTP服务, 面板反向代理转发

单写者约定:
- plugin_control.json   只有面板写
- plugin_status.json    只有机器人写
- plugins/<name>/config.json  机器人运行时只有机器人写(面板经 set_config 命令委托)
- package.json 的 enabled 字段只有面板写(机器人不落盘回写)
"""
import json
import os
import time
import uuid
import threading
import logging
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CONTROL_FILE = "plugin_control.json"
STATUS_FILE = "plugin_status.json"
API_HOST = "127.0.0.1"
API_PORT = 9528
COMMAND_EXPIRE = 60        # 命令过期秒数(防僵尸命令)
POLL_INTERVAL = 2.0        # 机器人轮询间隔(秒)
STATUS_HEARTBEAT = 10.0    # 状态心跳周期(秒)


def atomic_write_json(path, data):
    """原子写 JSON: 同目录 .tmp(唯一名) + os.replace, 避免读者读到半截文件"""
    try:
        dir_path = os.path.dirname(os.path.abspath(path)) or "."
        # 唯一临时名, 防止并发写时互相覆盖
        tmp_path = os.path.join(dir_path, f".{os.path.basename(path)}.{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logging.error(f"原子写 {path} 失败: {str(e)}")
        return False


def safe_read_json(path, default):
    """容忍 IOError/ValueError 的 JSON 读取(损坏文件视为不存在)"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return default


class PluginBridge:
    """面板 <-> 机器人桥接器"""

    def __init__(self):
        self.api_server = None
        self._token = uuid.uuid4().hex          # 面板代理鉴权 token
        self._plugin_loader = None
        self._bot_manager = None
        self._last_command_id = None            # 命令去重(内存)
        self._running = False
        self._lock = threading.RLock()

    # ================= 面板侧接口 =================

    def send_command(self, command, plugin_name=None, config=None,
                     wait=True, timeout=10.0):
        """写控制命令; wait=True 时轮询 status 等机器人执行结果.
        返回 {'success': bool, 'message': str, 'executed': bool(机器人是否实际执行),
              'bot_running': bool, 'result': dict|None}"""
        with self._lock:
            command_id = uuid.uuid4().hex
            cmd = {
                "id": command_id,
                "command": command,
                "plugin": plugin_name,
                "config": config,
                "timestamp": time.time(),
                "expires_at": time.time() + COMMAND_EXPIRE
            }
            bot_running = self.is_bot_alive()
            try:
                atomic_write_json(CONTROL_FILE, cmd)
            except Exception as e:
                return {'success': False, 'message': f'写入控制命令失败: {str(e)}',
                        'executed': False, 'bot_running': bot_running, 'result': None}

            if not bot_running:
                return {'success': True,
                        'message': '机器人未运行，命令已记录，将在下次启动时生效',
                        'executed': False, 'bot_running': False, 'result': None}

            if wait:
                result = self.wait_command_result(command_id, timeout)
                if result:
                    return {'success': result.get('success', True),
                            'message': result.get('message', '命令已执行'),
                            'executed': True, 'bot_running': True, 'result': result}
                return {'success': True, 'message': '命令已下发(等待执行结果超时)',
                        'executed': False, 'bot_running': True, 'result': None}
            return {'success': True, 'message': '命令已下发',
                    'executed': False, 'bot_running': True, 'result': None}

    def wait_command_result(self, command_id, timeout=10.0):
        """每 0.5s 读 status, 直到 last_command.id == command_id; 超时返回 None"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.read_status()
            last = status.get('last_command') or {}
            if last.get('id') == command_id and last.get('finished_at'):
                return last
            time.sleep(0.5)
        return None

    def read_status(self):
        """读状态快照; 文件不存在/损坏返回默认结构"""
        status = safe_read_json(STATUS_FILE, None)
        if not isinstance(status, dict):
            status = {}
        status.setdefault('bot_running', False)
        status.setdefault('plugins', {})
        return status

    def is_bot_alive(self):
        """status.bot_running 且 updated_at 距今 < 15 秒"""
        status = self.read_status()
        if not status.get('bot_running'):
            return False
        updated = status.get('updated_at', 0)
        return time.time() - updated < 15

    def get_api_token(self):
        """从 status 文件取 token(机器人未运行时返回空串)"""
        status = self.read_status()
        api_server = status.get('api_server') or {}
        return api_server.get('token', '')

    def proxy_api(self, plugin_name, path, method='GET', body=None, timeout=5.0):
        """面板请求机器人插件 API. 返回 (http_status, dict).
        机器人未运行/连接失败/超时 -> (503, 友好 JSON)"""
        token = self.get_api_token()
        if not token or not self.is_bot_alive():
            return 503, {'success': False, 'message': '机器人未运行或插件API服务不可用'}
        try:
            headers = {'X-Plugin-Token': token}
            if plugin_name:
                url = f"http://{API_HOST}:{API_PORT}/api/{plugin_name}{path}"
            else:
                url = f"http://{API_HOST}:{API_PORT}{path}"
            if method.upper() == 'GET':
                resp = requests.get(url, headers=headers, timeout=timeout)
            else:
                resp = requests.post(url, headers=headers, json=(body or {}),
                                     timeout=timeout)
            try:
                return resp.status_code, resp.json()
            except ValueError:
                return resp.status_code, {'success': False, 'message': resp.text}
        except requests.RequestException as e:
            logging.error(f"插件API代理失败: {str(e)}")
            return 503, {'success': False, 'message': f'插件API服务不可用: {str(e)}'}

    # ================= 机器人侧接口 =================

    def start(self, plugin_loader, bot_manager):
        """幂等启动: 控制轮询线程 + API服务器线程(daemon); 启动后立刻刷新状态"""
        with self._lock:
            if self._running:
                return True
            self._running = True
            self._plugin_loader = plugin_loader
            self._bot_manager = bot_manager
            threading.Thread(target=self.control_loop, daemon=True,
                             name="plugin-bridge-control").start()
            threading.Thread(target=self.start_api_server, daemon=True,
                             name="plugin-bridge-api").start()
            self.refresh_status()
            return True

    def shutdown(self):
        """停 API 服务器, 写 bot_running=False 终态"""
        with self._lock:
            self._running = False
            self.stop_api_server()
            atomic_write_json(STATUS_FILE, {
                'bot_pid': os.getpid(),
                'bot_running': False,
                'updated_at': time.time(),
                'api_server': {'running': False, 'port': API_PORT, 'token': ''},
                'last_command': self.read_status().get('last_command'),
                'plugins': {}
            })

    def control_loop(self):
        """轮询线程主体: 每 2s 读控制文件 -> 校验 -> 执行 -> 刷新状态; 每 10s 心跳"""
        last_heartbeat = 0
        while self._running:
            try:
                cmd = safe_read_json(CONTROL_FILE, None)
                if isinstance(cmd, dict) and cmd.get('id'):
                    expires = cmd.get('expires_at', 0)
                    if cmd['id'] != self._last_command_id and time.time() < expires:
                        result = self._execute_command(cmd)
                        result['finished_at'] = time.time()
                        result['id'] = cmd['id']
                        result['command'] = cmd.get('command')
                        result['plugin'] = cmd.get('plugin')
                        self._last_command_id = cmd['id']
                        self.refresh_status(extra={'last_command': result})
                now = time.time()
                if now - last_heartbeat >= STATUS_HEARTBEAT:
                    self.refresh_status()
                    last_heartbeat = now
            except Exception as e:
                logging.error(f"控制轮询异常: {str(e)}")
            time.sleep(POLL_INTERVAL)

    def _execute_command(self, cmd):
        """分发并执行命令. 机器人不写 package.json(enabled 以面板写入的文件为准)"""
        command = cmd.get('command')
        plugin_name = cmd.get('plugin')
        loader = self._plugin_loader
        try:
            if command == 'enable':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                ok = loader.load_plugin(plugin_name)
                return {'success': ok, 'message': f"插件 {plugin_name} 已加载" if ok
                        else f"插件 {plugin_name} 加载失败"}
            elif command == 'disable':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                ok = loader.unload_plugin(plugin_name)
                return {'success': ok, 'message': f"插件 {plugin_name} 已卸载" if ok
                        else f"插件 {plugin_name} 卸载失败"}
            elif command == 'load':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                ok = loader.load_plugin(plugin_name)
                return {'success': ok, 'message': f"插件 {plugin_name} 加载成功" if ok
                        else f"插件 {plugin_name} 加载失败"}
            elif command == 'unload':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                ok = loader.unload_plugin(plugin_name)
                return {'success': ok, 'message': f"插件 {plugin_name} 卸载成功" if ok
                        else f"插件 {plugin_name} 卸载失败"}
            elif command == 'reload':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                ok = loader.reload_plugin(plugin_name)
                return {'success': ok, 'message': f"插件 {plugin_name} 重载成功" if ok
                        else f"插件 {plugin_name} 重载失败"}
            elif command == 'reload_all':
                ok = loader.reload_all()
                return {'success': ok, 'message': '全部插件已重载' if ok else '部分插件重载失败'}
            elif command == 'set_config':
                if not plugin_name:
                    return {'success': False, 'message': '缺少插件名'}
                return self._apply_plugin_config(plugin_name, cmd.get('config'))
            else:
                return {'success': False, 'message': f'未知命令: {command}'}
        except Exception as e:
            logging.error(f"执行插件命令失败: {str(e)}")
            return {'success': False, 'message': f'执行失败: {str(e)}'}

    def _apply_plugin_config(self, plugin_name, config):
        """机器人侧写插件 config.json(原子写) 并重载插件"""
        if config is None:
            return {'success': False, 'message': '缺少配置内容'}
        config_path = os.path.join("plugins", plugin_name, "config.json")
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path + ".tmp", 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            os.replace(config_path + ".tmp", config_path)
        except Exception as e:
            return {'success': False, 'message': f'写配置失败: {str(e)}'}
        ok = self._plugin_loader.reload_plugin(plugin_name)
        return {'success': ok, 'message': f"插件 {plugin_name} 配置已保存并重载" if ok
                else f"配置已保存但插件 {plugin_name} 重载失败"}

    def refresh_status(self, extra=None):
        """从 plugin_loader 拉取每插件状态写 status 文件(机器人侧调用)"""
        plugins = {}
        api_running = self.api_server is not None
        if self._plugin_loader:
            for plugin in self._plugin_loader.get_all_plugins():
                entry = {
                    'enabled': plugin.enabled,
                    'loaded': plugin.instance is not None,
                    'version': plugin.metadata.get('version', '1.0.0'),
                    'error': plugin.load_error,
                    'loaded_at': time.time() if plugin.instance else None,
                    'api_routes': list(getattr(plugin.instance, 'api_routes', {}).keys())
                                  if plugin.instance else [],
                    'commands': [(cmd, info.get('description', ''))
                                 for cmd, info in
                                 getattr(plugin.instance, 'command_handlers', {}).items()]
                                if plugin.instance else []
                }
                plugins[plugin.name] = entry
        status = {
            'bot_pid': os.getpid(),
            'bot_running': self._running,
            'updated_at': time.time(),
            'api_server': {'running': api_running, 'port': API_PORT,
                           'token': self._token if api_running else ''},
            'plugins': plugins
        }
        if extra:
            status.update(extra)
        else:
            # 心跳刷新时保留上一次命令结果(避免面板轮询时丢失)
            prev = self.read_status().get('last_command')
            if prev:
                status['last_command'] = prev
        atomic_write_json(STATUS_FILE, status)

    def start_api_server(self):
        """ThreadingHTTPServer 仅绑 127.0.0.1; 端口占用时记录日志不崩主流程"""
        # 先置哨兵值, 让 refresh_status 立即把 token 写入状态文件(线程绑定有延迟)
        self.api_server = True
        try:
            handler = self._make_handler()
            self.api_server = ThreadingHTTPServer((API_HOST, API_PORT), handler)
            self.api_server.serve_forever()
        except OSError as e:
            logging.error(f"插件API服务器启动失败(端口 {API_PORT} 被占用?): {str(e)}")
            self.api_server = None

    def _make_handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 覆写为空, 避免污染机器人日志

            def _check_token(self):
                return self.headers.get('X-Plugin-Token') == bridge._token

            def _send_json(self, status, data):
                body = json.dumps(data, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._route('GET')

            def do_POST(self):
                self._route('POST')

            def _route(self, method):
                try:
                    if not self._check_token():
                        return self._send_json(403, {'success': False, 'message': '鉴权失败'})
                    parsed = urlparse(self.path)
                    path = parsed.path
                    query = parse_qs(parsed.query)
                    loader = bridge._plugin_loader
                    if path == '/health':
                        return self._send_json(200, {
                            'ok': True, 'pid': os.getpid(),
                            'plugins': len(loader.get_all_plugins()) if loader else 0})
                    if path == '/plugins':
                        info = []
                        if loader:
                            for p in loader.get_all_plugins():
                                if p.instance:
                                    info.append({
                                        'name': p.name,
                                        'version': p.metadata.get('version', '1.0.0'),
                                        'api_routes': list(getattr(p.instance, 'api_routes', {}).keys()),
                                        'commands': list(getattr(p.instance, 'command_handlers', {}).keys())
                                    })
                        return self._send_json(200, {'success': True, 'plugins': info})
                    if path == '/metrics':
                        data = {}
                        if loader:
                            for p in loader.get_all_plugins():
                                if not p.instance:
                                    continue
                                if query.get('plugin') and query['plugin'][0] != p.name:
                                    continue
                                try:
                                    data[p.name] = {
                                        'metrics': p.instance.collect_metrics(),
                                        'dashboard': p.instance.create_dashboard_data()
                                    }
                                except Exception as e:
                                    data[p.name] = {'metrics': {}, 'error': str(e)}
                        return self._send_json(200, {'success': True, 'data': data})
                    if path.startswith('/api/'):
                        parts = path[5:].split('/', 1)
                        if len(parts) != 2:
                            return self._send_json(404, {'success': False, 'message': '路径无效'})
                        plugin_name, sub_path = parts
                        if not loader:
                            return self._send_json(404, {'success': False, 'message': '插件加载器不可用'})
                        plugin = loader.get_plugin(plugin_name)
                        if not plugin or not plugin.instance:
                            return self._send_json(404, {'success': False,
                                                         'message': f'插件 {plugin_name} 未加载'})
                        body = {}
                        if method == 'POST':
                            try:
                                length = int(self.headers.get('Content-Length', 0))
                                raw = self.rfile.read(length) if length else b'{}'
                                body = json.loads(raw.decode('utf-8'))
                            except ValueError:
                                body = {}
                        # query 参数合并进 body
                        body.update({k: v[0] if len(v) == 1 else v for k, v in query.items()})
                        result = plugin.instance.handle_api_request('/' + sub_path, method, body)
                        if result is None:
                            return self._send_json(404, {'success': False, 'message': '路由不存在'})
                        if isinstance(result, dict):
                            return self._send_json(200, result)
                        return self._send_json(200, {'success': True, 'data': result})
                    return self._send_json(404, {'success': False, 'message': '未知路径'})
                except Exception as e:
                    try:
                        return self._send_json(500, {'success': False, 'message': f'服务器内部错误: {str(e)}'})
                    except Exception:
                        pass

        return Handler

    def stop_api_server(self):
        """停 API 服务器"""
        server = self.api_server
        if server and server is not True:  # True 是启动中的哨兵值
            try:
                server.shutdown()
                server.server_close()
            except Exception as e:
                logging.error(f"停插件API服务器失败: {str(e)}")
        self.api_server = None


# 全局单例
_bridge = PluginBridge()


def get_bridge():
    """获取全局桥接单例"""
    return _bridge
