# [file name]: web_panel.py
# [file content begin]
import json
import os
import logging
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess
import signal
import psutil
import init

# 导入现有的配置管理
import ConfigManage

init.init_manage()

app = Flask(__name__)
app.secret_key = 'bilibili_bot_panel_secret_key_2024'

# 面板配置
PANEL_CONFIG_FILE = "panel_config.json"
LOG_FILE = "bot_runtime.log"

# 全局变量
bot_process = None
is_bot_running = False
bot_logs = []

class PanelConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self):
        """加载面板配置文件"""
        default_config = {
            "admin": {
                "username": "admin",
                "password": generate_password_hash("admin123")
            },
            "bot_settings": {
                "poll_interval": 5
            }
        }
        
        if not os.path.exists(self.config_path):
            self.config = default_config
            self.save_config()
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self.config = default_config
            self.save_config()
            return default_config
    
    def save_config(self):
        """保存面板配置"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
    
    def get_admin_credentials(self):
        """获取管理员凭据"""
        return self.config.get("admin", {})
    
    def update_admin_credentials(self, username, password):
        """更新管理员凭据"""
        if "admin" not in self.config:
            self.config["admin"] = {}
        
        self.config["admin"]["username"] = username
        if password:  # 只有当密码不为空时才更新密码
            self.config["admin"]["password"] = generate_password_hash(password)
        self.save_config()

# 初始化配置管理器
panel_config = PanelConfigManager(PANEL_CONFIG_FILE)
bot_config = ConfigManage.ConfigManager("config.json")

# 日志处理
class LogHandler:
    def __init__(self, log_file):
        self.log_file = log_file
        self.logs = []
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """确保日志文件存在"""
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"Bot Log File Created at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    def add_log(self, message, level="INFO"):
        """添加日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        
        # 添加到内存日志
        self.logs.append(log_entry)
        if len(self.logs) > 1000:  # 限制内存中日志数量
            self.logs = self.logs[-500:]
        
        # 写入文件
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    
    def get_logs(self, limit=100):
        """获取最新的日志"""
        return self.logs[-limit:] if self.logs else []

# 登录装饰器
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# 路由定义
@app.route('/')
@login_required
def index():
    """主控制面板"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin_creds = panel_config.get_admin_credentials()
        
        if (username == admin_creds.get('username') and 
            check_password_hash(admin_creds.get('password'), password)):
            session['logged_in'] = True
            session['username'] = username
            log_handler.add_log(f"用户 {username} 登录成功")
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='用户名或密码错误')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """退出登录"""
    username = session.get('username', '未知用户')
    session.clear()
    log_handler.add_log(f"用户 {username} 退出登录")
    return redirect(url_for('login'))

@app.route('/api/bot_status')
@login_required
def get_bot_status():
    """获取机器人状态"""
    global is_bot_running
    
    # 检查进程是否还在运行
    if bot_process and bot_process.poll() is None:
        is_bot_running = True
    else:
        is_bot_running = False
    
    return jsonify({
        'running': is_bot_running,
        'config': bot_config.get("config", {}),
        'keywords': bot_config.get("keyword", {})
    })

@app.route('/api/start_bot', methods=['POST'])
@login_required
def start_bot():
    """启动机器人"""
    global bot_process, is_bot_running
    
    if is_bot_running:
        return jsonify({'success': False, 'message': '机器人已在运行中'})
    
    try:
        # 检查Python解释器路径
        python_path = 'python'
        if os.path.exists('.venv/bin/python'):
            python_path = '.venv/bin/python'
        elif os.path.exists('venv/bin/python'):
            python_path = 'venv/bin/python'
        
        # 启动机器人进程
        bot_process = subprocess.Popen(
            [python_path, 'index.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # 启动日志读取线程
        threading.Thread(target=read_bot_output, daemon=True).start()
        
        is_bot_running = True
        log_handler.add_log("机器人启动成功")
        
        return jsonify({'success': True, 'message': '机器人启动成功'})
    
    except Exception as e:
        log_handler.add_log(f"机器人启动失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'启动失败: {str(e)}'})

@app.route('/api/stop_bot', methods=['POST'])
@login_required
def stop_bot():
    """停止机器人"""
    global bot_process, is_bot_running
    
    if not is_bot_running:
        return jsonify({'success': False, 'message': '机器人未在运行'})
    
    try:
        # 终止进程
        if bot_process:
            bot_process.terminate()
            try:
                bot_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bot_process.kill()
                bot_process.wait()
        
        is_bot_running = False
        log_handler.add_log("机器人已停止")
        
        return jsonify({'success': True, 'message': '机器人已停止'})
    
    except Exception as e:
        log_handler.add_log(f"机器人停止失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'停止失败: {str(e)}'})

def read_bot_output():
    """读取机器人输出"""
    global bot_process
    if bot_process and bot_process.stdout:
        for line in iter(bot_process.stdout.readline, ''):
            if line:
                log_handler.add_log(f"BOT: {line.strip()}")

@app.route('/api/update_config', methods=['POST'])
@login_required
def update_config():
    """更新机器人配置"""
    try:
        config_data = request.json
        
        # 更新配置
        for key, value in config_data.items():
            bot_config.set(key, value)
        
        log_handler.add_log("机器人配置已更新")
        return jsonify({'success': True, 'message': '配置更新成功'})
    
    except Exception as e:
        log_handler.add_log(f"配置更新失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/api/update_keywords', methods=['POST'])
@login_required
def update_keywords():
    """更新关键词配置"""
    try:
        keywords_data = request.json
        
        # 更新关键词
        bot_config.set("keyword", keywords_data)
        
        log_handler.add_log("关键词配置已更新")
        return jsonify({'success': True, 'message': '关键词更新成功'})
    
    except Exception as e:
        log_handler.add_log(f"关键词更新失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/api/add_keyword', methods=['POST'])
@login_required
def add_keyword():
    """添加单个关键词"""
    try:
        keyword = request.json.get('keyword')
        reply = request.json.get('reply')
        
        if not keyword or not reply:
            return jsonify({'success': False, 'message': '关键词和回复内容不能为空'})
        
        # 获取当前关键词
        current_keywords = bot_config.get("keyword", {})
        current_keywords[keyword] = reply
        
        # 更新配置
        bot_config.set("keyword", current_keywords)
        
        log_handler.add_log(f"添加关键词: {keyword} -> {reply}")
        return jsonify({'success': True, 'message': '关键词添加成功'})
    
    except Exception as e:
        log_handler.add_log(f"关键词添加失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'})

@app.route('/api/delete_keyword', methods=['POST'])
@login_required
def delete_keyword():
    """删除关键词"""
    try:
        keyword = request.json.get('keyword')
        
        if not keyword:
            return jsonify({'success': False, 'message': '关键词不能为空'})
        
        # 获取当前关键词
        current_keywords = bot_config.get("keyword", {})
        
        if keyword in current_keywords:
            del current_keywords[keyword]
            # 更新配置
            bot_config.set("keyword", current_keywords)
            log_handler.add_log(f"删除关键词: {keyword}")
            return jsonify({'success': True, 'message': '关键词删除成功'})
        else:
            return jsonify({'success': False, 'message': '关键词不存在'})
    
    except Exception as e:
        log_handler.add_log(f"关键词删除失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/api/get_logs')
@login_required
def get_logs():
    """获取日志"""
    limit = request.args.get('limit', 100, type=int)
    logs = log_handler.get_logs(limit)
    return jsonify({'logs': logs})

@app.route('/api/update_admin', methods=['POST'])
@login_required
def update_admin():
    """更新管理员账号密码"""
    try:
        username = request.json.get('username')
        current_password = request.json.get('current_password')
        new_password = request.json.get('new_password')
        
        # 验证当前密码
        admin_creds = panel_config.get_admin_credentials()
        if not check_password_hash(admin_creds.get('password'), current_password):
            return jsonify({'success': False, 'message': '当前密码错误'})
        
        # 更新凭据
        panel_config.update_admin_credentials(username, new_password)
        
        # 更新会话中的用户名
        session['username'] = username
        
        log_handler.add_log("管理员账号信息已更新")
        return jsonify({'success': True, 'message': '账号信息更新成功'})
    
    except Exception as e:
        log_handler.add_log(f"管理员账号更新失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

# 创建模板目录和文件
def create_templates():
    """创建HTML模板文件"""
    templates_dir = 'templates'
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    # 创建基础模板
    with open(os.path.join(templates_dir, 'base.html'), 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}B站私信机器人控制面板{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        primary: {
                            50: '#f0f9ff',
                            100: '#e0f2fe',
                            200: '#bae6fd',
                            300: '#7dd3fc',
                            400: '#38bdf8',
                            500: '#0ea5e9',
                            600: '#0284c7',
                            700: '#0369a1',
                            800: '#075985',
                            900: '#0c4a6e',
                        },
                        bilibili: '#00A1D6'
                    },
                    fontFamily: {
                        'sans': ['Inter', 'system-ui', 'sans-serif'],
                    }
                }
            }
        }
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        .gradient-bg {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        .card-hover {
            transition: all 0.3s ease;
        }
        
        .card-hover:hover {
            transform: translateY(-5px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        }
        
        .sidebar-transition {
            transition: all 0.3s ease;
        }
        
        .log-entry {
            border-left: 3px solid transparent;
            padding-left: 12px;
            margin-bottom: 8px;
        }
        
        .log-entry.info {
            border-left-color: #3b82f6;
            background-color: #eff6ff;
        }
        
        .log-entry.error {
            border-left-color: #ef4444;
            background-color: #fef2f2;
        }
        
        .log-entry.success {
            border-left-color: #10b981;
            background-color: #ecfdf5;
        }
        
        .log-entry.warning {
            border-left-color: #f59e0b;
            background-color: #fffbeb;
        }
    </style>
</head>
<body class="bg-gray-50 font-sans">
    {% block content %}{% endblock %}
    
    <script src="https://unpkg.com/htmx.org@1.9.6"></script>
</body>
</html>''')
    
    # 创建登录页面
    with open(os.path.join(templates_dir, 'login.html'), 'w', encoding='utf-8') as f:
        f.write('''{% extends "base.html" %}

{% block content %}
<div class="min-h-screen flex items-center justify-center gradient-bg py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
        <div class="bg-white rounded-2xl shadow-xl p-8">
            <div class="text-center">
                <div class="mx-auto h-16 w-16 bg-bilibili rounded-full flex items-center justify-center">
                    <i class="fa fa-robot text-white text-2xl"></i>
                </div>
                <h2 class="mt-6 text-3xl font-bold text-gray-900">
                    B站私信机器人
                </h2>
                <p class="mt-2 text-sm text-gray-600">
                    控制面板登录
                </p>
            </div>
            <form class="mt-8 space-y-6" method="POST">
                {% if error %}
                <div class="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg flex items-center">
                    <i class="fa fa-exclamation-circle mr-2"></i>
                    {{ error }}
                </div>
                {% endif %}
                
                <div class="space-y-4">
                    <div>
                        <label for="username" class="block text-sm font-medium text-gray-700 mb-2">用户名</label>
                        <div class="relative">
                            <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                <i class="fa fa-user text-gray-400"></i>
                            </div>
                            <input id="username" name="username" type="text" required 
                                   class="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="请输入用户名">
                        </div>
                    </div>
                    <div>
                        <label for="password" class="block text-sm font-medium text-gray-700 mb-2">密码</label>
                        <div class="relative">
                            <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                <i class="fa fa-lock text-gray-400"></i>
                            </div>
                            <input id="password" name="password" type="password" required 
                                   class="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="请输入密码">
                        </div>
                    </div>
                </div>

                <div>
                    <button type="submit" 
                            class="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-white bg-bilibili hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition transform hover:-translate-y-0.5">
                        <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                            <i class="fa fa-sign-in-alt text-blue-300 group-hover:text-blue-200"></i>
                        </span>
                        登录系统
                    </button>
                </div>
                
                <div class="text-center text-sm text-gray-500">
                    <p>默认账号: admin / admin123</p>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}''')
    
    # 创建主控制面板
    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('''<!-- [file name]: templates/index.html -->
<!-- [file content begin] -->
{% extends "base.html" %}

{% block content %}
<div class="flex h-screen bg-gray-50">
    <!-- 侧边栏 -->
    <div id="sidebar" class="sidebar-transition w-64 bg-white shadow-xl lg:shadow-lg fixed lg:relative inset-y-0 left-0 z-40 transform -translate-x-full lg:translate-x-0">
        <div class="p-6 border-b border-gray-100">
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 bg-bilibili rounded-lg flex items-center justify-center">
                    <i class="fa fa-robot text-white"></i>
                </div>
                <div>
                    <h1 class="text-lg font-bold text-gray-800">B站机器人</h1>
                    <p class="text-xs text-gray-500">控制面板</p>
                </div>
            </div>
            <p class="text-sm text-gray-600 mt-2">欢迎, <span class="font-medium">{{ session.username }}</span></p>
        </div>
        
        <nav class="mt-6 px-3">
            <a href="#dashboard" onclick="showSection('dashboard')" class="nav-item active flex items-center space-x-3 px-4 py-3 text-gray-700 bg-primary-50 rounded-xl border border-primary-100">
                <i class="fa fa-chart-pie text-primary-600 w-5"></i>
                <span>控制台</span>
            </a>
            <a href="#config" onclick="showSection('config')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-cog text-gray-400 w-5"></i>
                <span>机器人配置</span>
            </a>
            <a href="#keywords" onclick="showSection('keywords')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-key text-gray-400 w-5"></i>
                <span>关键词管理</span>
            </a>
            <a href="#logs" onclick="showSection('logs')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-terminal text-gray-400 w-5"></i>
                <span>运行日志</span>
            </a>
            <a href="#admin" onclick="showSection('admin')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-user-shield text-gray-400 w-5"></i>
                <span>账号设置</span>
            </a>
            <a href="/logout" class="nav-item flex items-center space-x-3 px-4 py-3 text-red-600 hover:bg-red-50 rounded-lg transition mt-4">
                <i class="fa fa-sign-out-alt w-5"></i>
                <span>退出登录</span>
            </a>
        </nav>
    </div>

    <!-- 遮罩层 -->
    <div id="overlay" class="fixed inset-0 bg-black bg-opacity-50 z-30 lg:hidden" style="display: none;"></div>

    <!-- 主内容区 -->
    <div class="flex-1 overflow-auto lg:ml-0">
        <!-- 控制台 -->
        <div id="dashboard" class="section active p-4 lg:p-6">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 - 放在标题栏左边 -->
                    <button id="mobile-menu-button" class="lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">控制台</h2>
                        <p class="text-gray-600 mt-2">机器人运行状态监控和管理</p>
                    </div>
                </div>
            </div>

            <!-- 状态卡片 -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 lg:gap-6 mb-6">
                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 card-hover">
                    <div class="flex items-center">
                        <div class="p-3 rounded-xl bg-blue-100 text-blue-600">
                            <i class="fa fa-robot text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">运行状态</h3>
                            <p id="status-text" class="text-2xl font-semibold text-gray-800">检查中...</p>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 card-hover">
                    <div class="flex items-center">
                        <div class="p-3 rounded-xl bg-green-100 text-green-600">
                            <i class="fa fa-key text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">关键词数量</h3>
                            <p id="keyword-count" class="text-2xl font-semibold text-gray-800">0</p>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 card-hover">
                    <div class="flex items-center">
                        <div class="p-3 rounded-xl bg-purple-100 text-purple-600">
                            <i class="fa fa-clock text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">最后更新</h3>
                            <p id="last-update" class="text-lg font-semibold text-gray-800">--</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 控制按钮 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
                <h3 class="text-lg font-medium text-gray-800 mb-4">机器人控制</h3>
                <div class="flex flex-col sm:flex-row space-y-3 sm:space-y-0 sm:space-x-4">
                    <button id="start-btn" onclick="startBot()" 
                            class="flex items-center justify-center px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition transform hover:-translate-y-0.5">
                        <i class="fa fa-play mr-2"></i>启动机器人
                    </button>
                    <button id="stop-btn" onclick="stopBot()" 
                            class="flex items-center justify-center px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition transform hover:-translate-y-0.5">
                        <i class="fa fa-stop mr-2"></i>停止机器人
                    </button>
                </div>
            </div>

            <!-- 快速操作 -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-4">快速操作</h3>
                    <div class="space-y-3">
                        <button onclick="showSection('config')" class="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition">
                            <div class="flex items-center space-x-3">
                                <i class="fa fa-cog text-gray-400"></i>
                                <span>修改配置</span>
                            </div>
                            <i class="fa fa-chevron-right text-gray-400"></i>
                        </button>
                        <button onclick="showSection('keywords')" class="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition">
                            <div class="flex items-center space-x-3">
                                <i class="fa fa-key text-gray-400"></i>
                                <span>管理关键词</span>
                            </div>
                            <i class="fa fa-chevron-right text-gray-400"></i>
                        </button>
                        <button onclick="showSection('logs')" class="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition">
                            <div class="flex items-center space-x-3">
                                <i class="fa fa-terminal text-gray-400"></i>
                                <span>查看日志</span>
                            </div>
                            <i class="fa fa-chevron-right text-gray-400"></i>
                        </button>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-4">系统信息</h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">面板版本</span>
                            <span class="font-medium">v1.0.0</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">运行时间</span>
                            <span id="uptime" class="font-medium">--</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">日志数量</span>
                            <span id="log-count" class="font-medium">--</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 配置管理 -->
        <div id="config" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 - 放在标题栏左边 -->
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">机器人配置</h2>
                        <p class="text-gray-600 mt-2">修改B站账号相关配置</p>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <form id="config-form">
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">SESSDATA</label>
                            <input type="text" name="config_sessdata" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">BILI_JCT</label>
                            <input type="text" name="config_bili_jct" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">SELF_UID</label>
                            <input type="number" name="config_self_uid" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">DEVICE_ID</label>
                            <input type="text" name="config_device_id" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                        </div>
                    </div>
                    <div class="mt-6">
                        <button type="submit" 
                                class="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition transform hover:-translate-y-0.5">
                            <i class="fa fa-save mr-2"></i>保存配置
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <!-- 关键词管理 -->
        <div id="keywords" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 - 放在标题栏左边 -->
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">关键词管理</h2>
                        <p class="text-gray-600 mt-2">添加和管理自动回复关键词</p>
                    </div>
                </div>
            </div>

            <!-- 添加关键词表单 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
                <h3 class="text-lg font-medium text-gray-800 mb-4">添加新关键词</h3>
                <form id="add-keyword-form" class="grid grid-cols-1 lg:grid-cols-5 gap-4">
                    <div class="lg:col-span-2">
                        <label class="block text-sm font-medium text-gray-700 mb-2">关键词</label>
                        <input type="text" name="keyword" required
                               class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                               placeholder="例如: 你好">
                    </div>
                    <div class="lg:col-span-2">
                        <label class="block text-sm font-medium text-gray-700 mb-2">回复内容</label>
                        <input type="text" name="reply" required
                               class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                               placeholder="例如: 你好，我是自动回复机器人">
                    </div>
                    <div class="lg:col-span-1 flex items-end">
                        <button type="submit" 
                                class="w-full px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 transition transform hover:-translate-y-0.5">
                            <i class="fa fa-plus mr-2"></i>添加
                        </button>
                    </div>
                </form>
            </div>

            <!-- 关键词列表 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 class="text-lg font-medium text-gray-800">关键词列表</h3>
                    <span class="text-sm text-gray-500" id="keywords-count">共 0 个关键词</span>
                </div>
                <div id="keywords-list" class="p-6">
                    <div class="text-center text-gray-500 py-8">
                        <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                        <p>加载中...</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- 运行日志 -->
        <div id="logs" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 - 放在标题栏左边 -->
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">运行日志</h2>
                        <p class="text-gray-600 mt-2">实时查看机器人运行状态和日志</p>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm border border-gray-100">
                <div class="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 class="text-lg font-medium text-gray-800">日志记录</h3>
                    <div class="flex space-x-2">
                        <button onclick="fetchLogs()" 
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition">
                            <i class="fa fa-sync-alt mr-2"></i>刷新
                        </button>
                        <button onclick="clearLogs()" 
                                class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 transition">
                            <i class="fa fa-trash mr-2"></i>清空
                        </button>
                    </div>
                </div>
                <div class="p-6">
                    <div id="log-container" class="bg-gray-900 text-gray-300 font-mono text-sm rounded-lg p-4 h-96 overflow-y-auto">
                        <div class="text-center text-gray-500 py-8">
                            <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                            <p>正在加载日志...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 账号设置 -->
        <div id="admin" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 - 放在标题栏左边 -->
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">账号设置</h2>
                        <p class="text-gray-600 mt-2">修改控制面板登录信息</p>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <form id="admin-form">
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">用户名</label>
                            <input type="text" name="username" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   value="{{ session.username }}">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">当前密码</label>
                            <input type="password" name="current_password" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="请输入当前密码">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">新密码</label>
                            <input type="password" name="new_password"
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="留空则不修改密码">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">确认新密码</label>
                            <input type="password" name="confirm_password"
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="再次输入新密码">
                        </div>
                    </div>
                    <div class="mt-6">
                        <button type="submit" 
                                class="px-6 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition transform hover:-translate-y-0.5">
                            <i class="fa fa-save mr-2"></i>更新账号信息
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<script>
// 修复正则表达式转义问题
function parseConfigKey(key) {
    const match = key.match(/config_([a-z_]+)/);
    return match ? match[1] : null;
}

// 移动端菜单控制
document.addEventListener('DOMContentLoaded', function() {
    // 为所有移动端菜单按钮添加事件监听
    const menuButtons = document.querySelectorAll('#mobile-menu-button, .mobile-menu-button');
    menuButtons.forEach(button => {
        button.addEventListener('click', function() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('overlay');
            sidebar.classList.toggle('-translate-x-full');
            overlay.style.display = sidebar.classList.contains('-translate-x-full') ? 'none' : 'block';
        });
    });

    document.getElementById('overlay').addEventListener('click', function() {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.add('-translate-x-full');
        this.style.display = 'none';
    });
});

// 显示指定部分，隐藏其他部分
function showSection(sectionId) {
    // 隐藏所有部分
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
    
    // 显示选中的部分
    document.getElementById(sectionId).style.display = 'block';
    
    // 更新导航项状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active', 'bg-primary-50', 'border', 'border-primary-100', 'text-gray-700');
        item.classList.add('text-gray-600', 'hover:bg-gray-50');
    });
    
    // 找到被点击的导航项并激活它
    const clickedNav = document.querySelector(`[href="#${sectionId}"]`);
    if (clickedNav) {
        clickedNav.classList.add('active', 'bg-primary-50', 'border', 'border-primary-100', 'text-gray-700');
        clickedNav.classList.remove('text-gray-600', 'hover:bg-gray-50');
    }

    // 特殊处理：如果是日志部分，开始轮询日志
    if (sectionId === 'logs') {
        startLogPolling();
    } else {
        stopLogPolling();
    }
    
    // 在移动端选择后关闭菜单
    if (window.innerWidth < 1024) {
        document.getElementById('sidebar').classList.add('-translate-x-full');
        document.getElementById('overlay').style.display = 'none';
    }
}

// 启动日志轮询
function startLogPolling() {
    if (window.logInterval) clearInterval(window.logInterval);
    fetchLogs();
    window.logInterval = setInterval(fetchLogs, 2000);
}

// 停止日志轮询
function stopLogPolling() {
    if (window.logInterval) {
        clearInterval(window.logInterval);
        window.logInterval = null;
    }
}

// 获取日志
function fetchLogs() {
    fetch('/api/get_logs?limit=100')
        .then(response => response.json())
        .then(data => {
            const logContainer = document.getElementById('log-container');
            if (logContainer) {
                if (data.logs && data.logs.length > 0) {
                    logContainer.innerHTML = data.logs.map(log => {
                        let logClass = 'info';
                        let icon = 'fa fa-info-circle text-blue-400';
                        
                        if (log.includes('ERROR') || log.includes('错误') || log.includes('失败')) {
                            logClass = 'error';
                            icon = 'fa fa-exclamation-circle text-red-400';
                        } else if (log.includes('成功') || log.includes('SUCCESS')) {
                            logClass = 'success';
                            icon = 'fa fa-check-circle text-green-400';
                        } else if (log.includes('警告') || log.includes('WARNING')) {
                            logClass = 'warning';
                            icon = 'fa fa-exclamation-triangle text-yellow-400';
                        } else if (log.includes('BOT:')) {
                            logClass = 'bot';
                            icon = 'fa fa-robot text-purple-400';
                        }
                        
                        return `
                            <div class="log-entry ${logClass} flex items-start space-x-2 py-1 border-l-4 border-${logClass === 'error' ? 'red' : logClass === 'success' ? 'green' : logClass === 'warning' ? 'yellow' : logClass === 'bot' ? 'purple' : 'blue'}-500 pl-3 mb-2">
                                <i class="${icon} mt-1 flex-shrink-0"></i>
                                <span class="flex-1">${log}</span>
                            </div>
                        `;
                    }).join('');
                    logContainer.scrollTop = logContainer.scrollHeight;
                } else {
                    logContainer.innerHTML = '<div class="text-center text-gray-500 py-8">暂无日志</div>';
                }
            }
        })
        .catch(error => {
            console.error('获取日志失败:', error);
            const logContainer = document.getElementById('log-container');
            if (logContainer) {
                logContainer.innerHTML = '<div class="text-center text-red-500 py-8">获取日志失败</div>';
            }
        });
}

// 清空日志
function clearLogs() {
    if (confirm('确定要清空所有日志吗？')) {
        const logContainer = document.getElementById('log-container');
        if (logContainer) {
            logContainer.innerHTML = '<div class="text-center text-gray-500 py-8">日志已清空</div>';
        }
    }
}

// 获取机器人状态
function fetchBotStatus() {
    fetch('/api/bot_status')
        .then(response => response.json())
        .then(data => {
            // 更新状态显示
            const statusText = document.getElementById('status-text');
            const startBtn = document.getElementById('start-btn');
            const stopBtn = document.getElementById('stop-btn');
            const keywordCount = document.getElementById('keyword-count');
            const keywordsCount = document.getElementById('keywords-count');
            
            if (data.running) {
                statusText.innerHTML = '<span class="text-green-600 flex items-center"><i class="fa fa-circle animate-pulse mr-2"></i>运行中</span>';
                startBtn.disabled = true;
                stopBtn.disabled = false;
            } else {
                statusText.innerHTML = '<span class="text-red-600 flex items-center"><i class="fa fa-circle mr-2"></i>已停止</span>';
                startBtn.disabled = false;
                stopBtn.disabled = true;
            }
            
            // 更新关键词数量
            const keywordCountValue = Object.keys(data.keywords || {}).length;
            keywordCount.textContent = keywordCountValue;
            if (keywordsCount) {
                keywordsCount.textContent = `共 ${keywordCountValue} 个关键词`;
            }
            
            // 更新最后更新时间
            document.getElementById('last-update').textContent = new Date().toLocaleString();
            
            // 更新系统信息
            document.getElementById('log-count').textContent = keywordCountValue;
            
            // 如果是在配置页面，更新表单数据
            if (document.getElementById('config').style.display !== 'none') {
                updateConfigForm(data.config);
            }
            
            // 如果是在关键词页面，更新关键词列表
            if (document.getElementById('keywords').style.display !== 'none') {
                updateKeywordsList(data.keywords);
            }
        })
        .catch(error => {
            console.error('获取机器人状态失败:', error);
            const statusText = document.getElementById('status-text');
            if (statusText) {
                statusText.innerHTML = '<span class="text-red-600">获取状态失败</span>';
            }
        });
}

// 更新配置表单
function updateConfigForm(config) {
    if (config) {
        for (const key in config) {
            const input = document.querySelector(`[name="config_${key}"]`);
            if (input) {
                input.value = config[key] || '';
            }
        }
    }
}

// 更新关键词列表
function updateKeywordsList(keywords) {
    const container = document.getElementById('keywords-list');
    if (!container) return;
    
    if (!keywords || Object.keys(keywords).length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-8"><i class="fa fa-inbox text-3xl mb-3"></i><p>暂无关键词</p></div>';
        return;
    }
    
    container.innerHTML = Object.entries(keywords).map(([keyword, reply]) => `
        <div class="flex items-center justify-between p-4 border border-gray-200 rounded-lg mb-3 bg-white hover:bg-gray-50 transition">
            <div class="flex-1">
                <div class="font-medium text-gray-800 flex items-center">
                    <i class="fa fa-key text-primary-600 mr-2"></i>
                    ${keyword}
                </div>
                <div class="text-sm text-gray-600 mt-1 flex items-center">
                    <i class="fa fa-reply text-gray-400 mr-2"></i>
                    ${reply}
                </div>
            </div>
            <button onclick="deleteKeyword('${keyword}')" 
                    class="ml-4 px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 transition transform hover:scale-105">
                <i class="fa fa-trash"></i>
            </button>
        </div>
    `).join('');
}

// 启动机器人
function startBot() {
    fetch('/api/start_bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('启动机器人失败:', error);
            showNotification('启动机器人失败，请检查网络连接', 'error');
        });
}

// 停止机器人
function stopBot() {
    fetch('/api/stop_bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('停止机器人失败:', error);
            showNotification('停止机器人失败，请检查网络连接', 'error');
        });
}

// 删除关键词
function deleteKeyword(keyword) {
    if (confirm(`确定要删除关键词 "${keyword}" 吗？`)) {
        fetch('/api/delete_keyword', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('删除关键词失败:', error);
            showNotification('删除关键词失败，请检查网络连接', 'error');
        });
    }
}

// 显示通知
function showNotification(message, type = 'info') {
    // 创建通知元素
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-500' : 
                   type === 'error' ? 'bg-red-500' : 
                   'bg-blue-500';
    const icon = type === 'success' ? 'fa-check' : 
                type === 'error' ? 'fa-exclamation-triangle' : 
                'fa-info';
    
    notification.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg z-50 max-w-sm transform transition-transform duration-300 translate-x-full ${bgColor} text-white`;
    notification.innerHTML = `
        <div class="flex items-center">
            <i class="fa ${icon} mr-3"></i>
            <span class="flex-1">${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 text-white hover:text-gray-200">
                <i class="fa fa-times"></i>
            </button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // 显示通知
    setTimeout(() => {
        notification.classList.remove('translate-x-full');
    }, 100);
    
    // 5秒后隐藏并移除
    setTimeout(() => {
        notification.classList.add('translate-x-full');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 5000);
}

// 表单提交处理
document.getElementById('config-form')?.addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = new FormData(this);
    const config = {};
    
    for (let [key, value] of formData.entries()) {
        const configKey = parseConfigKey(key);
        if (configKey) {
            config[configKey] = value;
        }
    }
    
    fetch('/api/update_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            fetchBotStatus();
        }
    })
    .catch(error => {
        console.error('更新配置失败:', error);
        showNotification('更新配置失败，请检查网络连接', 'error');
    });
});

document.getElementById('add-keyword-form')?.addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = new FormData(this);
    const data = {
        keyword: formData.get('keyword'),
        reply: formData.get('reply')
    };
    
    if (!data.keyword.trim() || !data.reply.trim()) {
        showNotification('关键词和回复内容不能为空', 'error');
        return;
    }
    
    fetch('/api/add_keyword', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            this.reset();
            fetchBotStatus();
        }
    })
    .catch(error => {
        console.error('添加关键词失败:', error);
        showNotification('添加关键词失败，请检查网络连接', 'error');
    });
});

document.getElementById('admin-form')?.addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = new FormData(this);
    const data = {
        username: formData.get('username'),
        current_password: formData.get('current_password'),
        new_password: formData.get('new_password')
    };
    
    if (data.new_password && data.new_password !== formData.get('confirm_password')) {
        showNotification('新密码和确认密码不匹配', 'error');
        return;
    }
    
    fetch('/api/update_admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            // 更新页面上的用户名显示
            const usernameElements = document.querySelectorAll('.username-display');
            usernameElements.forEach(el => {
                el.textContent = data.username || formData.get('username');
            });
        }
    })
    .catch(error => {
        console.error('更新账号信息失败:', error);
        showNotification('更新账号信息失败，请检查网络连接', 'error');
    });
});

// 计算运行时间
function updateUptime() {
    const startTime = new Date();
    setInterval(() => {
        const now = new Date();
        const diff = now - startTime;
        const hours = Math.floor(diff / 3600000);
        const minutes = Math.floor((diff % 3600000) / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        
        const uptimeElement = document.getElementById('uptime');
        if (uptimeElement) {
            uptimeElement.textContent = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
    }, 1000);
}

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    // 开始状态轮询
    setInterval(fetchBotStatus, 3000);
    fetchBotStatus();
    
    // 初始化运行时间
    updateUptime();
    
    // 设置默认激活的导航项
    const defaultNav = document.querySelector('.nav-item.active');
    if (defaultNav) {
        defaultNav.click();
    }
    
    // 添加用户名显示类
    const usernameElements = document.querySelectorAll('.username-display');
    usernameElements.forEach(el => {
        el.textContent = '{{ session.username }}';
    });
});
</script>
{% endblock %}
<!-- [file content end] -->''')

if __name__ == '__main__':
    # 创建模板文件
    create_templates()
    
    # 启动Flask应用
    print("正在启动B站私信机器人控制面板...")
    print("访问地址: http://127.0.0.1:5000")
    print("默认账号: admin")
    print("默认密码: admin123")
    print("请及时修改默认密码！")
    
    # 关闭调试模式，避免重启
    app.run(debug=False, host='0.0.0.0', port=5000)
# [file content end]