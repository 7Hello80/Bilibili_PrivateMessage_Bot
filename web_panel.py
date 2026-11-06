import json
import os
import logging
import secrets
import string
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess
import psutil
import init
import sys
import uuid
import requests
import qrcode
import base64
from io import BytesIO
import platform
from colorama import Fore, Back, Style
import distro
import mimetypes
import bili_ticket
from plugin_loader import plugin_loader
from plugin_manage import plugin_manager
from plugin_dev import PluginDeveloper
from plugin_create import plugin_creator
import plugin_bridge
from plugin_bridge import get_bridge
import github
from github import Github
from github_source import github_source
import plugin_tasks

# 导入现有的配置管理
import ConfigManage

CURRENT_VERSION = "MS4xLjQ="
UPDATE_CHECK_URL = "aHR0cDovLzExNC4xMzQuMTg4LjE4OD9pZD0x"
Version = "2.0.5"
system_name = platform.system()
system_version = platform.version()
# 磁盘统计路径：Termux 上优先统计用户共享存储，其他平台回退到根目录
disk_default = "/storage/emulated/0/"
if not os.path.isdir(disk_default):
    disk_default = "/"

if system_name == "Linux":
    #获取linux发行版名称
    system_distribution = distro.name()
else:
    system_distribution = system_name + " " + platform.release()

init.init_manage()

app = Flask(__name__)


def _load_or_create_secret_key():
    """读取面板会话密钥。

    优先使用环境变量 PANEL_SECRET_KEY；否则读取本地 .panel_secret 文件，
    首次运行时自动生成随机密钥（该文件已被 .gitignore 忽略，切勿提交）。
    """
    env_key = os.environ.get("PANEL_SECRET_KEY")
    if env_key:
        return env_key

    key_file = ".panel_secret"
    try:
        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                saved = f.read().strip()
            if len(saved) >= 32:
                return saved
        new_key = secrets.token_hex(32)
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(new_key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return new_key
    except OSError:
        # 无法持久化时退回进程内随机密钥（重启后需要重新登录）
        return secrets.token_hex(32)


app.secret_key = _load_or_create_secret_key()

# 面板配置
PANEL_CONFIG_FILE = "panel_config.json"
LOG_FILE = "bot_runtime.log"

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
            },
            "github": {
                "client_id": "",
                "client_secret": "",
                "access_token": "",
                "repo_owner": "7Hello80",
                "repo_name": "Bilibili_PrivateMessage_Bot"
            }
        }
        
        if not os.path.exists(self.config_path):
            self.config = default_config
            self.save_config()
            return default_config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保github配置存在
                if "github" not in config:
                    config["github"] = default_config["github"]
                return config
        except (json.JSONDecodeError, FileNotFoundError):
            self.config = default_config
            self.save_config()
            return default_config
    
    def check_for_updates(self):
        """检查更新"""
        try:
            response = requests.get(ConfigManage.base64_decode(UPDATE_CHECK_URL), timeout=10)
            if response.status_code == 200:
                update_info = response.json()
                return {
                    'has_update': update_info.get('version') != ConfigManage.base64_decode(CURRENT_VERSION),
                    'update_info': update_info,
                    'current_version': ConfigManage.base64_decode(CURRENT_VERSION)
                }
        except Exception as e:
            logging.error(f"检查更新失败: {str(e)}")
        return {
            'has_update': False,
            'update_info': None,
            'current_version': ConfigManage.base64_decode(CURRENT_VERSION)
        }
    
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
    
    def get_github_config(self):
        """获取GitHub配置"""
        return self.config.get("github", {})
    
    def update_github_config(self, client_id, client_secret, access_token="", repo_owner="", repo_name=""):
        """更新GitHub配置"""
        if "github" not in self.config:
            self.config["github"] = {}
        
        github_config = self.config["github"]
        if client_id:
            github_config["client_id"] = client_id
        if client_secret:
            github_config["client_secret"] = client_secret
        if access_token:
            github_config["access_token"] = access_token
        if repo_owner:
            github_config["repo_owner"] = repo_owner
        if repo_name:
            github_config["repo_name"] = repo_name
        
        self.save_config()
    
    def update_github_token(self, access_token):
        """更新GitHub访问令牌"""
        if "github" not in self.config:
            self.config["github"] = {}
        
        self.config["github"]["access_token"] = access_token
        self.save_config()

    def get_github_source(self):
        """获取 GitHub 加速源配置(默认 auto: 官方优先, 失败自动换源)"""
        source = self.config.get("github_source")
        return source if isinstance(source, dict) else {}

    def update_github_source(self, source_config):
        """更新 GitHub 加速源配置(整段覆盖, 仅保留已知字段)"""
        if not isinstance(source_config, dict):
            return
        allowed = ("mode", "mirror", "custom_prefix", "connect_timeout", "stall_timeout")
        self.config["github_source"] = {k: source_config[k] for k in allowed if k in source_config}
        self.save_config()

# 全局变量
bot_process = None
is_bot_running = False
bot_logs = []

class GitHubDiscussionManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.github_client = None
        self.repo = None
        self._init_github_client()
    
    def _init_github_client(self):
        """初始化GitHub客户端"""
        github_config = self.config_manager.get_github_config()
        access_token = github_config.get("access_token")
        
        if access_token:
            try:
                try:
                    from github import Auth
                    auth = Auth.Token(access_token)
                    self.github_client = Github(auth=auth)
                except (ImportError, AttributeError):
                    # 如果新方式不可用，回退到旧方式
                    self.github_client = Github(access_token)
                    logging.warning("使用旧的GitHub认证方式，建议升级PyGithub库")
                repo_owner = github_config.get("repo_owner", "7Hello80")
                repo_name = github_config.get("repo_name", "Bilibili_PrivateMessage_Bot")
                self.repo = self.github_client.get_repo(f"{repo_owner}/{repo_name}")
            except Exception as e:
                logging.error(f"初始化GitHub客户端失败: {str(e)}")
                self.github_client = None
                self.repo = None
    
    def is_authenticated(self):
        """检查是否已认证"""
        return self.github_client is not None and self.repo is not None
    
    def get_discussions(self, category=None, state="open", limit=20):
        """获取讨论列表"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            # GitHub API目前没有直接的discussions端点，我们使用issues作为替代
            # 实际项目中需要根据GitHub Discussions API调整
            issues = self.repo.get_issues(state=state, sort="created", direction="desc")
            
            discussions = []
            for issue in issues[:limit]:
                discussions.append({
                    "id": issue.id,
                    "number": issue.number,
                    "title": issue.title,
                    "body": issue.body,
                    "state": issue.state,
                    "user": {
                        "login": issue.user.login,
                        "avatar_url": issue.user.avatar_url
                    },
                    "created_at": issue.created_at.isoformat(),
                    "updated_at": issue.updated_at.isoformat(),
                    "comments_count": issue.comments,
                    "labels": [label.name for label in issue.labels]
                })
            
            return {
                "success": True,
                "discussions": discussions
            }
        except Exception as e:
            logging.error(f"获取讨论列表失败: {str(e)}")
            return {"success": False, "message": f"获取讨论列表失败: {str(e)}"}
    
    def get_discussion(self, discussion_number):
        """获取单个讨论详情"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            issue = self.repo.get_issue(discussion_number)
            comments = []
            
            # 获取评论
            for comment in issue.get_comments():
                comments.append({
                    "id": comment.id,
                    "body": comment.body,
                    "user": {
                        "login": comment.user.login,
                        "avatar_url": comment.user.avatar_url
                    },
                    "created_at": comment.created_at.isoformat(),
                    "updated_at": comment.updated_at.isoformat()
                })
            
            discussion = {
                "id": issue.id,
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "state": issue.state,
                "user": {
                    "login": issue.user.login,
                    "avatar_url": issue.user.avatar_url
                },
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "comments_count": issue.comments,
                "labels": [label.name for label in issue.labels],
                "comments": comments
            }
            
            return {
                "success": True,
                "discussion": discussion
            }
        except Exception as e:
            logging.error(f"获取讨论详情失败: {str(e)}")
            return {"success": False, "message": f"获取讨论详情失败: {str(e)}"}
    
    def create_discussion(self, title, body, labels=None):
        """创建新讨论"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            issue = self.repo.create_issue(title=title, body=body, labels=labels or [])
            
            return {
                "success": True,
                "message": "讨论创建成功",
                "discussion": {
                    "id": issue.id,
                    "number": issue.number,
                    "title": issue.title
                }
            }
        except Exception as e:
            logging.error(f"创建讨论失败: {str(e)}")
            return {"success": False, "message": f"创建讨论失败: {str(e)}"}
    
    def create_comment(self, discussion_number, body):
        """在讨论中创建评论"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            issue = self.repo.get_issue(discussion_number)
            comment = issue.create_comment(body)
            
            return {
                "success": True,
                "message": "评论发布成功",
                "comment": {
                    "id": comment.id,
                    "body": comment.body
                }
            }
        except Exception as e:
            logging.error(f"发布评论失败: {str(e)}")
            return {"success": False, "message": f"发布评论失败: {str(e)}"}
    
    def get_user_info(self):
        """获取当前用户信息"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            user = self.github_client.get_user()
            return {
                "success": True,
                "user": {
                    "login": user.login,
                    "name": user.name,
                    "avatar_url": user.avatar_url,
                    "html_url": user.html_url
                }
            }
        except Exception as e:
            logging.error(f"获取用户信息失败: {str(e)}")
            return {"success": False, "message": f"获取用户信息失败: {str(e)}"}
    

    def delete_comment(self, discussion_number, comment_id):
        """删除评论"""
        if not self.is_authenticated():
            return {"success": False, "message": "GitHub未认证"}
        
        try:
            issue = self.repo.get_issue(discussion_number)
            comment = issue.get_comment(comment_id)
            
            # 获取当前用户以验证权限
            current_user = self.github_client.get_user().login
            if comment.user.login != current_user:
                return {
                    "success": False, 
                    "message": "只能删除自己的评论"
                }
            
            # 删除评论
            comment.delete()
            
            return {
                "success": True,
                "message": "评论删除成功"
            }
        except github.GithubException as e:
            if e.status == 404:
                return {"success": False, "message": "评论不存在"}
            elif e.status == 403:
                return {"success": False, "message": "没有删除权限"}
            else:
                logging.error(f"删除评论失败: {str(e)}")
                return {"success": False, "message": f"删除评论失败: {str(e)}"}
        except Exception as e:
            logging.error(f"删除评论失败: {str(e)}")
            return {"success": False, "message": f"删除评论失败: {str(e)}"}

# 初始化GitHub讨论区管理器
panel_config = PanelConfigManager(PANEL_CONFIG_FILE)
github_manager = GitHubDiscussionManager(panel_config)

# 把面板配置注入 GitHub 加速源（避免 github_source 模块与 web_panel 循环导入）
github_source.bind_config(panel_config)


# 初始化配置管理器
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
    
    def clear_logs(self):
        """清除所有日志"""
        try:
            # 清空内存中的日志
            self.logs = []
            
            # 清空日志文件
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"Logs cleared at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
            # 添加一条清除记录
            self.add_log("日志已被管理员清除", "INFO")
            return True
        except Exception as e:
            logging.error(f"清除日志失败: {str(e)}")
            return False

# 初始化日志处理器
log_handler = LogHandler(LOG_FILE)

def restart_bot_mod():
    """重启机器人"""
    global bot_process, is_bot_running
    
    try:
        # 先停止机器人
        if is_bot_running and bot_process:
            bot_process.terminate()
            try:
                bot_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bot_process.kill()
                bot_process.wait()
            is_bot_running = False
            # 补写终态状态快照
            try:
                get_bridge().shutdown()
            except Exception:
                pass

        # 等待一下确保进程完全停止
        time.sleep(2)

        # 清理残留控制命令
        try:
            if os.path.exists(plugin_bridge.CONTROL_FILE):
                os.remove(plugin_bridge.CONTROL_FILE)
        except OSError:
            pass

        # 再启动机器人
        python_path = get_python3_path()
        if not python_path:
            log_handler.add_log("未找到python3解释器", "ERROR")

        bot_process = subprocess.Popen(
            [python_path, 'index.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            bufsize=1
        )
        
        # 启动日志读取线程
        threading.Thread(target=read_bot_output, daemon=True).start()
        
        is_bot_running = True
    
    except Exception as e:
        log_handler.add_log(f"机器人重启失败: {str(e)}", "ERROR")

def generate_qr_base64(url):
    """生成二维码并返回Base64字符串"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()

# 登录装饰器
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_python3_path():
    def is_python3(cmd):
        try:
            # 用universal_newlines替代text，兼容Python 3.7以下版本
            result = subprocess.run(
                [cmd, '--version'],
                stdout=subprocess.PIPE,  # 捕获标准输出
                stderr=subprocess.PIPE,  # 捕获标准错误（Python版本信息常输出到这里）
                universal_newlines=True,  # 替代text=True，将输出转为字符串
                timeout=5
            )
            # 合并输出
            version_output = result.stdout + result.stderr
            return 'Python 3' in version_output
        except Exception as e:
            return False
    
    # 1. 优先检查宝塔面板Python的常见安装路径（根据实际路径调整）
    baota_python_paths = [
        '/www/server/python3/bin/python3',  # 宝塔常见路径
        '/usr/local/bin/python3',
        '/www/server/python/bin/python3'
    ]
    for path in baota_python_paths:
        if os.path.exists(path) and is_python3(path):
            return path
    
    # 2. 检查虚拟环境
    venv_dirs = ['.venv', 'venv', 'env']
    for venv_dir in venv_dirs:
        if sys.platform == "win32":
            paths = [f'{venv_dir}/Scripts/python.exe', f'{venv_dir}/Scripts/python']
        else:
            paths = [f'{venv_dir}/bin/python', f'{venv_dir}/bin/python3']
        
        for path in paths:
            if os.path.exists(path) and is_python3(path):
                return path
    
    # 3. 检查系统命令（补充宝塔路径到环境变量）
    if sys.platform != "win32":
        os.environ["PATH"] += ":/www/server/python3/bin:/usr/local/bin"
        commands = ['python3', 'python']
    else:
        commands = ['python']
    
    for cmd in commands:
        if is_python3(cmd):
            return cmd
    
    return None

# 多账号管理路由
@app.route('/api/get_accounts')
@login_required
def get_accounts():
    """获取所有账号"""
    accounts = bot_config.get_accounts()
    global_keywords = bot_config.get_global_keywords()
    return jsonify({
        'code': '0',
        'accounts': accounts,
        'global_keywords': global_keywords
    })

@app.route('/api/add_account', methods=['POST'])
@login_required
def add_account():
    """添加新账号"""
    try:
        account_data = request.json
        
        # 创建新账号配置
        new_account = {
            "name": account_data.get("name", "新账号"),
            "config": {
                "sessdata": account_data.get("sessdata", ""),
                "bili_jct": account_data.get("bili_jct", ""),
                "self_uid": account_data.get("self_uid", 0),
                "device_id": account_data.get("device_id", str(uuid.uuid4()).upper()),
                "DedeUserID": account_data.get("DedeUserID", ""),
                "DedeUserID__ckMd5": account_data.get("DedeUserID__ckMd5", ""),
                "sid": account_data.get("sid", "")
            },
            "keyword": account_data.get("keywords", {}),
            "at_user": account_data.get("at_user", False),
            "auto_focus": account_data.get("auto_focus", False),
            "auto_reply_follow": account_data.get("auto_reply_follow", False),  # 新增
            "no_focus_hf": account_data.get("no_focus_hf", False),
            "follow_reply_message": account_data.get("follow_reply_message", "感谢关注！"),  # 新增
            "enabled": account_data.get("enabled", True)
        }
        
        bot_config.add_account(new_account)
        log_handler.add_log(f"添加新账号: {new_account['name']}")
        restart_bot_mod()
        return jsonify({'success': True, 'message': '账号添加成功'})
    
    except Exception as e:
        log_handler.add_log(f"添加账号失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'})

# 将图片上传到哔哩哔哩图床
@app.route('/api/upload_bfs', methods=['POST'])
@login_required
def upload_bfs():
    # 1. 基础参数校验
    api = "https://api.bilibili.com/x/dynamic/feed/draw/upload_bfs"
    file = request.files.get("file_up")  # 获取前端上传的文件
    account_index = request.form.get("account_index", type=int, default=0)
    
    # 校验文件是否存在
    if not file or file.filename == '':
        return jsonify({"code": -1, "message": "未获取到有效图片文件"}), 400
    
    try:
        # 获取账号配置
        accounts = bot_config.get_accounts()
        if account_index < 0 or account_index >= len(accounts):
            return jsonify({"code": -2, "message": "账号索引无效"}), 400
        
        account = accounts[account_index]
        account_config = account.get("config", {})
        
        sessdata = account_config.get("sessdata", "")
        bili_jct = account_config.get("bili_jct", "")
        
        if not sessdata or not bili_jct:
            return jsonify({"code": -3, "message": "所选账号的Cookie信息不完整"}), 400
        
        # 2. 构造请求参数
        # 构造文件参数
        files = {
            "file_up": (
                file.filename,  # 文件名
                file.stream,    # 文件流
                file.mimetype   # MIME类型
            )
        }
        
        # 构造表单数据
        data = {
            "category": "daily",  # 日常类型
            "csrf": bili_jct,     # CSRF Token
            "biz": "im"           # 业务类型
        }
        
        # 3. 构造请求头和Cookie
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com"
        }
        
        # 传递登录Cookie
        request_cookies = {
            "SESSDATA": sessdata,
            "bili_jct": bili_jct,
            "bili_ticket": bili_ticket.get()
        }
        
        # 4. 发送请求到Bilibili API
        response = requests.post(
            url=api,
            files=files,
            data=data,
            cookies=request_cookies,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        
        # 5. 解析响应
        result = response.json()
        
        if result.get("code") == 0:
            data = result.get("data", {})
            image_url = data.get("image_url", "")
            
            if image_url:
                # 保存图片信息到配置
                image_data = {
                    "url": image_url,
                    "name": file.filename,
                    "size": request.content_length or 0,
                    "upload_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "upload_account": account.get("name", f"账号{account_index+1}")
                }
                
                bot_config.add_image(image_data)
                log_handler.add_log(f"图片上传成功: {file.filename} -> {image_url}")
                
                return jsonify({
                    "code": 0,
                    "message": "上传成功",
                    "data": {
                        "image_url": image_url,
                        "image_width": data.get("image_width", 0),
                        "image_height": data.get("image_height", 0)
                    }
                })
            else:
                return jsonify({"code": -8, "message": "上传成功但未获取到图片URL"}), 500
        else:
            error_msg = result.get("message", "未知错误")
            return jsonify({"code": result.get("code", -9), "message": f"B站API返回错误: {error_msg}"}), 500
        
    except requests.exceptions.HTTPError as e:
        log_handler.add_log(f"上传图片HTTP错误: {str(e)}", "ERROR")
        return jsonify({"code": -5, "message": f"API请求失败: {str(e)}"}), 500
    except requests.exceptions.JSONDecodeError:
        log_handler.add_log("上传图片响应非JSON格式", "ERROR")
        return jsonify({"code": -6, "message": "API返回非JSON数据", "data": response.text}), 500
    except Exception as e:
        log_handler.add_log(f"上传图片内部错误: {str(e)}", "ERROR")
        return jsonify({"code": -7, "message": f"服务器内部错误: {str(e)}"}), 500

@app.route('/api/check_update')
@login_required
def check_update():
    """检查更新"""
    try:
        update_info = panel_config.check_for_updates()
        return jsonify({
            'success': True,
            'has_update': update_info['has_update'],
            'update_info': update_info['update_info'],
            'current_version': update_info['current_version']
        })
    except Exception as e:
        log_handler.add_log(f"检查更新失败: {str(e)}", "ERROR")
        return jsonify({
            'success': False, 
            'message': f'检查更新失败: {str(e)}'
        })

@app.route('/api/update_account/<int:account_index>', methods=['POST'])
@login_required
def update_account(account_index):
    """更新账号配置"""
    try:
        account_data = request.json
        
        # 获取原有账号的关键词
        existing_account = bot_config.get_account(account_index)
        existing_keywords = existing_account.get("keyword", {})
        
        updated_account = {
            "name": account_data.get("name", f"账号{account_index+1}"),
            "config": {
                "sessdata": account_data.get("sessdata", ""),
                "bili_jct": account_data.get("bili_jct", ""),
                "self_uid": account_data.get("self_uid", 0),
                "device_id": account_data.get("device_id", ""),
                "DedeUserID": account_data.get("DedeUserID", ""),
                "DedeUserID__ckMd5": account_data.get("DedeUserID__ckMd5", ""),
                "sid": account_data.get("sid", "")
            },
            "keyword": existing_keywords,  # 保留原有的关键词，不覆盖
            "at_user": account_data.get("at_user", False),
            "auto_focus": account_data.get("auto_focus", False),
            "auto_reply_follow": account_data.get("auto_reply_follow", False),  # 新增
            "no_focus_hf": account_data.get("no_focus_hf", False),
            "follow_reply_message": account_data.get("follow_reply_message", "感谢关注！"),  # 新增
            "enabled": account_data.get("enabled", True)
        }
        
        bot_config.update_account(account_index, updated_account)
        log_handler.add_log(f"更新账号: {updated_account['name']}")
        restart_bot_mod()
        return jsonify({'success': True, 'message': '账号更新成功'})
    
    except Exception as e:
        log_handler.add_log(f"更新账号失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/api/delete_account/<int:account_index>', methods=['POST'])
@login_required
def delete_account(account_index):
    """删除账号"""
    try:
        accounts = bot_config.get_accounts()
        if 0 <= account_index < len(accounts):
            account_name = accounts[account_index].get("name", f"账号{account_index+1}")
            bot_config.delete_account(account_index)
            log_handler.add_log(f"删除账号: {account_name}")
            restart_bot_mod()
            return jsonify({'success': True, 'message': '账号删除成功'})
        else:
            return jsonify({'success': False, 'message': '账号不存在'})
    
    except Exception as e:
        log_handler.add_log(f"删除账号失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/api/toggle_account/<int:account_index>', methods=['POST'])
@login_required
def toggle_account(account_index):
    """启用/禁用账号"""
    try:
        accounts = bot_config.get_accounts()
        if 0 <= account_index < len(accounts):
            account = accounts[account_index]
            account["enabled"] = not account.get("enabled", True)
            bot_config.update_account(account_index, account)
            
            status = "启用" if account["enabled"] else "禁用"
            log_handler.add_log(f"{status}账号: {account.get('name', f'账号{account_index+1}')}")
            restart_bot_mod()
            return jsonify({'success': True, 'message': f'账号已{status}', 'enabled': account["enabled"]})
        else:
            return jsonify({'success': False, 'message': '账号不存在'})
    
    except Exception as e:
        log_handler.add_log(f"切换账号状态失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})

@app.route('/api/update_global_keywords', methods=['POST'])
@login_required
def update_global_keywords():
    """更新全局关键词"""
    try:
        keywords_data = request.json
        bot_config.set_global_keywords(keywords_data)
        
        log_handler.add_log("全局关键词配置已更新")
        restart_bot_mod()
        return jsonify({'success': True, 'message': '全局关键词更新成功'})
    
    except Exception as e:
        log_handler.add_log(f"全局关键词更新失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/api/add_account_keyword/<int:account_index>', methods=['POST'])
@login_required
def add_account_keyword(account_index):
    """为指定账号添加关键词"""
    try:
        keyword = request.json.get('keyword')
        reply = request.json.get('reply')
        
        if not keyword or not reply:
            return jsonify({'success': False, 'message': '关键词和回复内容不能为空'})
        
        bot_config.add_account_keyword(account_index, keyword, reply)
        restart_bot_mod()
        
        log_handler.add_log(f"为账号 {account_index} 添加关键词: {keyword} -> {reply}")
        return jsonify({'success': True, 'message': '关键词添加成功'})
    
    except Exception as e:
        log_handler.add_log(f"添加关键词失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'添加失败: {str(e)}'})

@app.route('/api/delete_account_keyword/<int:account_index>', methods=['POST'])
@login_required
def delete_account_keyword(account_index):
    """删除指定账号的关键词"""
    try:
        keyword = request.json.get('keyword')
        
        if not keyword:
            return jsonify({'success': False, 'message': '关键词不能为空'})
        
        bot_config.delete_account_keyword(account_index, keyword)
        restart_bot_mod()
        
        log_handler.add_log(f"从账号 {account_index} 删除关键词: {keyword}")
        return jsonify({'success': True, 'message': '关键词删除成功'})
    
    except Exception as e:
        log_handler.add_log(f"删除关键词失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

# 原有路由定义
@app.route('/')
@login_required
def index():
    """主控制面板"""
    return render_template('index.html')

# 哔哩哔哩扫码登录接口 - 申请登录二维码
@app.route('/api/bilibili_qrcode', methods=['GET'])
@login_required
def qrcode_login():
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://message.bilibili.com",
        "Referer": "https://message.bilibili.com/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        qrcode_data = response.json()
        
        if qrcode_data.get('code') != 0:
            log_handler.add_log(f"申请登录二维码失败: {qrcode_data.get('message')}", "ERROR")
            return jsonify({'success': False, 'message': f'申请登录二维码失败: {qrcode_data.get("message")}'})
        
        log_handler.add_log(f"申请登录二维码成功")
        return jsonify({'success': True, "data": {
            "qrcode_img": generate_qr_base64(qrcode_data.get("data", {})["url"]),
            "qrcode_key": qrcode_data.get("data", {})["qrcode_key"]
        }})
    except requests.RequestException as e:
        log_handler.add_log(f"申请登录二维码失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'申请登录二维码失败: {str(e)}'})

@app.route('/api/get_images')
@login_required
def get_images():
    """获取所有图片"""
    try:
        images = bot_config.get_images()
        return jsonify({'success': True, 'images': images})
    except Exception as e:
        log_handler.add_log(f"获取图片列表失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/delete_image', methods=['POST'])
@login_required
def delete_image():
    """删除图片"""
    try:
        image_url = request.json.get('image_url')
        if not image_url:
            return jsonify({'success': False, 'message': '图片URL不能为空'})
        
        bot_config.delete_image(image_url)
        log_handler.add_log(f"删除图片: {image_url}")
        return jsonify({'success': True, 'message': '图片删除成功'})
    
    except Exception as e:
        log_handler.add_log(f"删除图片失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})

@app.route('/api/save_image', methods=['POST'])
@login_required
def save_image():
    """保存图片信息到配置"""
    try:
        image_data = request.json
        if not image_data.get('url'):
            return jsonify({'success': False, 'message': '图片URL不能为空'})
        
        # 添加时间戳
        image_data['upload_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        success = bot_config.add_image(image_data)
        if success:
            log_handler.add_log(f"保存图片: {image_data['url']}")
            return jsonify({'success': True, 'message': '图片保存成功'})
        else:
            return jsonify({'success': False, 'message': '图片已存在'})
    
    except Exception as e:
        log_handler.add_log(f"保存图片失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'保存失败: {str(e)}'})

# 哔哩哔哩扫码登录接口 - 检查二维码登录状态
@app.route('/api/bilibili_qrcode_status', methods=['GET'])
@login_required
def qrcode_status():
    qrcode_key = request.args.get('qrcode_key')
    if not qrcode_key:
        return jsonify({'success': False, 'message': 'qrcode_key不能为空'})
    
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://message.bilibili.com",
        "Referer": "https://message.bilibili.com/",
    }
    
    params = {
        "qrcode_key": qrcode_key
    }
    
    try:
        # 使用 Session 保持会话
        session = requests.Session()
        response = session.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        status_data = response.json()
        
        data = status_data.get("data", {})
        status_code = data.get("code")
        
        if status_code == 0:
            # 登录成功，从响应的 cookies 中获取
            cookies_dict = session.cookies.get_dict()
            sessdata = cookies_dict.get('SESSDATA')
            bili_jct = cookies_dict.get('bili_jct')
            DedeUserID = cookies_dict.get("DedeUserID")
            DedeUserID__ckMd5 = cookies_dict.get("DedeUserID__ckMd5")
            sid = cookies_dict.get("sid")
            
            if not sessdata or not bili_jct:
                log_handler.add_log(f"登录成功但未获取到Cookie", "ERROR")
                return jsonify({'success': False, 'message': '登录成功但未获取到Cookie'})
            
            # 验证登录状态并获取用户信息
            user_api = "https://api.bilibili.com/x/web-interface/nav"
            user_headers = headers.copy()
            user_headers["Cookie"] = f"SESSDATA={sessdata}; bili_jct={bili_jct}; bili_ticket={bili_ticket.get()}"
            
            user_response = requests.get(user_api, headers=user_headers, timeout=10)
            user_response.raise_for_status()
            user_data = user_response.json()
            
            if user_data.get("code") != 0:
                log_handler.add_log(f"获取用户信息失败: {user_data.get('message')}", "ERROR")
                return jsonify({'success': False, 'message': f'获取用户信息失败: {user_data.get("message")}'})
            
            mid = user_data.get("data", {}).get("mid")
            uname = user_data.get("data", {}).get("uname", "")
            
            log_handler.add_log(f"账号登录成功: {uname}({mid})")
            return jsonify({
                'success': True, 
                'message': '登录成功',
                "data": {
                    "sessdata": sessdata,
                    "bili_jct": bili_jct,
                    "mid": mid,
                    "uname": uname,
                    "DedeUserID": DedeUserID,
                    "DedeUserID__ckMd5": DedeUserID__ckMd5,
                    "sid": sid
                }
            })
        elif status_code == 86101:
            return jsonify({'success': False, 'message': '二维码未扫描', 'code': 86101})
        elif status_code == 86038:
            return jsonify({'success': False, 'message': '二维码已过期', 'code': 86038})
        elif status_code == 86090:
            return jsonify({'success': False, 'message': '二维码已扫描未确认', 'code': 86090})
        else:
            message = data.get("message", "未知状态")
            return jsonify({'success': False, 'message': f'状态异常: {message}', 'code': status_code})
            
    except requests.RequestException as e:
        log_handler.add_log(f"检查登录状态失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'检查登录状态失败: {str(e)}'})

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

@app.route('/api/login', methods=['POST'])
def api_login():
    """API登录接口"""
    # 支持JSON和form两种格式
    if request.is_json:
        data = request.get_json()
        username = data.get('username') if data else None
        password = data.get('password') if data else None
    else:
        username = request.args.get('username')
        password = request.args.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'}), 400
    
    admin_creds = panel_config.get_admin_credentials()
    
    if (username == admin_creds.get('username') and 
        check_password_hash(admin_creds.get('password'), password)):
        # 设置session（与Web版完全相同）
        session['logged_in'] = True
        session['username'] = username
        log_handler.add_log(f"用户 {username} 通过API登录成功")
        
        return jsonify({
            'success': True,
            'message': '登录成功',
            'user': {'username': username}
        }), 200
    else:
        log_handler.add_log(f"API登录失败 - 用户名: {username}")
        return jsonify({
            'success': False,
            'error': '用户名或密码错误'
        }), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """API注销接口"""
    username = session.get('username', '未知用户')
    session.clear()
    log_handler.add_log(f"用户 {username} 通过API注销")
    
    return jsonify({
        'success': True,
        'message': '注销成功'
    }), 200

@app.route('/api/check', methods=['GET'])
def api_check():
    """检查登录状态"""
    if 'logged_in' in session and session['logged_in']:
        return jsonify({
            'logged_in': True,
            'user': {'username': session.get('username')}
        }), 200
    else:
        return jsonify({'logged_in': False}), 200

@app.route("/error", methods=['GET', 'POST'])
def Error():
    return render_template("error.html")

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
    
    # 获取账号信息
    accounts = bot_config.get_accounts()
    enabled_accounts = [acc for acc in accounts if acc.get("enabled", True)]
    
    return jsonify({
        'running': is_bot_running,
        'accounts': accounts,
        'enabled_accounts_count': len(enabled_accounts),
        'total_accounts_count': len(accounts),
        'global_keywords': bot_config.get_global_keywords()
    })

@app.route('/api/get_announcement', methods=['POST', 'GET'])
@login_required
def get_announcement():
    """获取远程公告"""
    try:
        response = requests.get(ConfigManage.base64_decode("aHR0cDovLzExNC4xMzQuMTg4LjE4OD9pZD0y"))
        response.raise_for_status()
        data = response.text
        return jsonify({'success': True, 'message': data})
    except requests.RequestException as e:
        log_handler.add_log(f"获取公告失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取公告失败: {str(e)}'})

@app.route('/api/start_bot', methods=['POST'])
@login_required
def start_bot():
    """启动机器人"""
    global bot_process, is_bot_running
    
    if is_bot_running:
        return jsonify({'success': False, 'message': '机器人已在运行中'})
    
    try:
        python_path = get_python3_path()
        if not python_path:
            log_handler.add_log("未找到python3解释器", "ERROR")
            return jsonify({'success': False, 'message': '未找到python3解释器'})

        # 启动前清理残留控制命令(避免僵尸命令被新机器人执行)
        try:
            if os.path.exists(plugin_bridge.CONTROL_FILE):
                os.remove(plugin_bridge.CONTROL_FILE)
        except OSError:
            pass

        # 启动机器人进程
        bot_process = subprocess.Popen(
            [python_path, 'index.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
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
        # 机器人被终止无法自写终态, 面板补写状态快照
        try:
            get_bridge().shutdown()
        except Exception:
            pass
        log_handler.add_log("机器人已停止")

        return jsonify({'success': True, 'message': '机器人已停止'})
    
    except Exception as e:
        log_handler.add_log(f"机器人停止失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'停止失败: {str(e)}'})

def _panel_github_token():
    """获取面板配置中的 GitHub token(可能为空)"""
    try:
        return panel_config.get_github_config().get('access_token', '')
    except Exception:
        return ''


@app.route('/api/plugins/search')
@login_required
def search_plugins():
    """搜索插件"""
    try:
        keyword = request.args.get('keyword', '')
        plugins = plugin_manager.search_plugins(keyword, _panel_github_token())
        return jsonify({'success': True, 'plugins': plugins})
    except Exception as e:
        log_handler.add_log(f"搜索插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'搜索失败: {str(e)}'})

@app.route('/api/plugins/lists')
@login_required
def plugins_list():
    try:
        plugins = plugin_manager.search_plugins('', _panel_github_token())
        return jsonify({'success': True, 'plugins': plugins})
    except Exception as e:
        log_handler.add_log(f"获取插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/install', methods=['POST'])
@login_required
def install_plugin():
    """创建插件安装任务：后台线程下载/校验/解压/热加载，前端轮询进度与日志。"""
    try:
        data = request.get_json(silent=True) or {}
        repo_full_name = str(data.get('repo_full_name') or '').strip()
        plugin_name = str(data.get('plugin_name') or '').strip()
        if not repo_full_name or not plugin_name:
            return jsonify({'success': False, 'message': '缺少仓库名或插件名'})
        if repo_full_name.count('/') != 1 or repo_full_name.startswith('/'):
            return jsonify({'success': False, 'message': '仓库名格式应为 owner/repo'})

        task = plugin_tasks.create_install_task(repo_full_name, plugin_name)
        log_handler.add_log(f"开始安装插件: {plugin_name}（任务 {task['id']}）")
        return jsonify({'success': True, 'message': '安装任务已创建', 'task': task})

    except Exception as e:
        log_handler.add_log(f"创建安装任务失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'创建安装任务失败: {str(e)}'})


@app.route('/api/plugins/install/<task_id>')
@login_required
def plugin_install_status(task_id):
    """查询安装任务进度。after 为已收到的日志序号，用于增量拉取。"""
    try:
        after = request.args.get('after', 0, type=int) or 0
        task = plugin_tasks.get_task(task_id, since=after)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在或已过期'}), 404
        return jsonify({'success': True, 'task': task})
    except Exception as e:
        return jsonify({'success': False, 'message': f'查询任务失败: {str(e)}'})


@app.route('/api/plugins/installs')
@login_required
def plugin_install_list():
    """列出最近的安装任务（页面刷新后用于恢复任务卡片）。"""
    try:
        limit = request.args.get('limit', 10, type=int) or 10
        limit = max(1, min(limit, plugin_tasks.MAX_TASKS))
        return jsonify({'success': True, 'tasks': plugin_tasks.list_tasks(limit=limit)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取任务列表失败: {str(e)}'})


@app.route('/api/plugins/install/<task_id>/cancel', methods=['POST'])
@login_required
def cancel_plugin_install(task_id):
    """取消安装任务（已进入解压/写入阶段的步骤会尽快停止）。"""
    try:
        ok = plugin_tasks.cancel_task(task_id)
        if not ok:
            return jsonify({'success': False, 'message': '任务不存在或已结束'})
        log_handler.add_log(f"已请求取消安装任务: {task_id}", "WARNING")
        return jsonify({'success': True, 'message': '已请求取消'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'取消失败: {str(e)}'})


@app.route('/api/github/source', methods=['GET'])
@login_required
def get_github_source_settings():
    """读取 GitHub 加速源设置、健康度与当前生效源。"""
    try:
        return jsonify({'success': True, **github_source.status()})
    except Exception as e:
        return jsonify({'success': False, 'message': f'读取加速源设置失败: {str(e)}'})


@app.route('/api/github/source', methods=['POST'])
@login_required
def set_github_source_settings():
    """切换加速源：auto=官方优先失败自动换源；manual=固定指定镜像。"""
    try:
        data = request.get_json(silent=True) or {}
        github_source.update_settings(
            mode=data.get('mode'),
            mirror=data.get('mirror'),
            custom_prefix=data.get('custom_prefix'),
            connect_timeout=data.get('connect_timeout'),
            stall_timeout=data.get('stall_timeout'),
        )
        settings = github_source.settings()
        log_handler.add_log(
            f"GitHub 加速源已更新: 模式={settings.get('mode')}, 源={settings.get('mirror')}")
        return jsonify({'success': True, 'message': '加速源设置已保存',
                        **github_source.status()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存加速源设置失败: {str(e)}'})


@app.route('/api/github/source/probe', methods=['POST'])
@login_required
def probe_github_sources():
    """并发测速所有可用源，返回首字节延迟。"""
    try:
        results = github_source.probe(timeout=8.0)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': f'测速失败: {str(e)}'})

@app.route('/api/plugins/uninstall', methods=['POST'])
@login_required
def uninstall_plugin():
    """卸载插件(先通知机器人卸载, 自动备份后删除)"""
    try:
        plugin_name = request.json.get('plugin_name')
        # 通知机器人进程卸载
        get_bridge().send_command('unload', plugin_name, wait=True)
        # 自动备份后删除
        plugin_manager.backup_plugin(plugin_name)
        if plugin_manager.delete_plugin(plugin_name):
            log_handler.add_log(f"卸载插件: {plugin_name}")
            return jsonify({'success': True, 'message': '插件卸载成功(已自动备份)'})
        else:
            return jsonify({'success': False, 'message': '插件卸载失败'})

    except Exception as e:
        log_handler.add_log(f"卸载插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'卸载失败: {str(e)}'})

@app.route('/api/plugins/list')
@login_required
def list_plugins():
    """获取已安装插件列表(合并机器人运行状态快照)"""
    try:
        plugins = plugin_manager.get_installed_plugins()
        status = get_bridge().read_status()
        bot_running = get_bridge().is_bot_alive()
        status_plugins = status.get('plugins', {})

        for plugin in plugins:
            sp = status_plugins.get(plugin['name'], {})
            plugin['loaded'] = sp.get('loaded', False)
            plugin['error'] = sp.get('error')
            plugin['api_routes'] = sp.get('api_routes', [])
            plugin['commands'] = sp.get('commands', [])
            plugin['bot_running'] = bot_running

        return jsonify({'success': True, 'plugins': plugins,
                        'bot_running': bot_running})
    except Exception as e:
        log_handler.add_log(f"获取插件列表失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/detail/<plugin_name>')
@login_required
def plugin_detail(plugin_name):
    """插件详情: 元数据 + README + 配置 + 备份列表 + 运行状态"""
    try:
        info = plugin_manager.get_plugin_info(plugin_name)
        if not info:
            return jsonify({'success': False, 'message': '插件不存在'})

        readme = ''
        readme_path = os.path.join(info['path'], "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, 'r', encoding='utf-8') as f:
                readme = f.read()

        config = {}
        config_path = os.path.join(info['path'], "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except ValueError:
                config = {}

        status = get_bridge().read_status()
        sp = status.get('plugins', {}).get(plugin_name, {})

        return jsonify({
            'success': True,
            'plugin': info,
            'readme': readme,
            'config': config,
            'backups': plugin_manager.list_backups(plugin_name),
            'status': sp,
            'bot_running': get_bridge().is_bot_alive()
        })
    except Exception as e:
        log_handler.add_log(f"获取插件详情失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/config', methods=['GET', 'POST'])
@login_required
def plugin_config():
    """插件配置读写(机器人运行时经 set_config 命令委托机器人写+重载)"""
    try:
        if request.method == 'GET':
            plugin_name = request.args.get('plugin_name', '')
            if not plugin_name:
                return jsonify({'success': False, 'message': '缺少插件名'})
            config_path = os.path.join("plugins", plugin_name, "config.json")
            config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except ValueError:
                    config = {}
            return jsonify({'success': True, 'config': config})

        # POST 保存
        data = request.json
        plugin_name = data.get('plugin_name')
        config = data.get('config')

        if not plugin_name:
            return jsonify({'success': False, 'message': '插件名称不能为空'})
        if not isinstance(config, dict):
            return jsonify({'success': False, 'message': '配置必须是 JSON 对象'})
        if not os.path.exists(os.path.join("plugins", plugin_name, "package.json")):
            return jsonify({'success': False, 'message': '插件不存在'})

        # 机器人运行时: 委托机器人写文件并重载(避免双进程写竞态)
        result = get_bridge().send_command('set_config', plugin_name, config=config, wait=True)
        if result.get('bot_running'):
            if result.get('executed') and result.get('result', {}).get('success'):
                log_handler.add_log(f"保存插件配置: {plugin_name}")
                return jsonify({'success': True, 'message': result['message']})
            return jsonify({'success': False, 'message': result.get('message', '保存失败')})

        # 机器人未运行: 面板直接原子写(下次启动生效)
        config_path = os.path.join("plugins", plugin_name, "config.json")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        tmp_path = config_path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, config_path)
        log_handler.add_log(f"保存插件配置(机器人未运行): {plugin_name}")
        return jsonify({'success': True,
                        'message': '配置已保存(机器人未运行，将在下次启动时生效)',
                        'bot_not_running': True})

    except Exception as e:
        log_handler.add_log(f"插件配置操作失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})

@app.route('/api/plugins/check_update', methods=['POST'])
@login_required
def check_plugin_update():
    """检查插件更新"""
    try:
        plugin_name = request.json.get('plugin_name')
        result = plugin_manager.check_plugin_update(plugin_name, _panel_github_token())
        return jsonify({'success': True, **result})
    except Exception as e:
        log_handler.add_log(f"检查插件更新失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'检查失败: {str(e)}'})

@app.route('/api/plugins/update', methods=['POST'])
@login_required
def update_plugin():
    """更新插件(先卸载通知, 备份后覆盖下载, 再通知加载)"""
    try:
        plugin_name = request.json.get('plugin_name')

        check = plugin_manager.check_plugin_update(plugin_name, _panel_github_token())
        if not check.get('has_update'):
            return jsonify({'success': False,
                            'message': check.get('message') or '没有可用更新'})

        # 通知机器人卸载
        get_bridge().send_command('unload', plugin_name, wait=True)

        if not plugin_manager.update_plugin(plugin_name, _panel_github_token()):
            return jsonify({'success': False, 'message': '更新失败(下载或校验未通过)'})

        # 通知机器人加载新版本
        get_bridge().send_command('load', plugin_name, wait=True)
        log_handler.add_log(f"更新插件: {plugin_name} -> v{check.get('latest_version')}")
        return jsonify({'success': True,
                        'message': f"插件已更新到 v{check.get('latest_version')}"})

    except Exception as e:
        log_handler.add_log(f"更新插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'更新失败: {str(e)}'})

@app.route('/api/plugins/backup', methods=['POST'])
@login_required
def backup_plugin():
    """备份插件"""
    try:
        plugin_name = request.json.get('plugin_name')
        backup_path = plugin_manager.backup_plugin(plugin_name)
        if backup_path:
            log_handler.add_log(f"备份插件: {plugin_name}")
            return jsonify({'success': True, 'message': f'备份成功: {os.path.basename(backup_path)}'})
        return jsonify({'success': False, 'message': '备份失败'})
    except Exception as e:
        log_handler.add_log(f"备份插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'备份失败: {str(e)}'})

@app.route('/api/plugins/backups')
@login_required
def list_plugin_backups():
    """插件备份列表"""
    try:
        plugin_name = request.args.get('plugin_name', '')
        return jsonify({'success': True,
                        'backups': plugin_manager.list_backups(plugin_name)})
    except Exception as e:
        log_handler.add_log(f"获取备份列表失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/restore', methods=['POST'])
@login_required
def restore_plugin():
    """从备份恢复插件"""
    try:
        data = request.json
        plugin_name = data.get('plugin_name')
        backup_file = data.get('backup_file')

        # 通知机器人卸载当前版本
        get_bridge().send_command('unload', plugin_name, wait=True)

        if plugin_manager.restore_plugin(plugin_name, backup_file):
            # 通知机器人加载恢复后的版本
            get_bridge().send_command('load', plugin_name, wait=True)
            log_handler.add_log(f"恢复插件: {plugin_name} <- {backup_file}")
            return jsonify({'success': True, 'message': '插件恢复成功'})
        return jsonify({'success': False, 'message': '恢复失败'})

    except Exception as e:
        log_handler.add_log(f"恢复插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'恢复失败: {str(e)}'})

@app.route('/api/plugins/reload_all', methods=['POST'])
@login_required
def reload_all_plugins():
    """重载全部插件"""
    try:
        result = get_bridge().send_command('reload_all', wait=True)
        if result.get('bot_running'):
            return jsonify({'success': result.get('executed', False),
                            'message': result.get('message', '已下发重载命令')})
        return jsonify({'success': True,
                        'message': '机器人未运行，将在下次启动时按最新配置加载',
                        'bot_not_running': True})
    except Exception as e:
        log_handler.add_log(f"重载全部插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'重载失败: {str(e)}'})

@app.route('/api/plugins/import', methods=['POST'])
@login_required
def import_plugin():
    """本地导入插件 zip"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未收到文件'})
        file = request.files['file']
        if not file.filename or not file.filename.lower().endswith('.zip'):
            return jsonify({'success': False, 'message': '只支持 .zip 文件'})

        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), f"plugin_import_{uuid.uuid4().hex}.zip")
        file.save(tmp_path)
        try:
            ok, result = plugin_manager.import_plugin_zip(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not ok:
            return jsonify({'success': False, 'message': f'导入失败: {result}'})

        # 通知机器人热加载
        get_bridge().send_command('load', result, wait=True)
        log_handler.add_log(f"导入插件: {result}")
        return jsonify({'success': True, 'message': f'插件 {result} 导入成功'})

    except Exception as e:
        log_handler.add_log(f"导入插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'})

@app.route('/api/plugins/edit/<plugin_name>', methods=['GET', 'POST'])
@login_required
def edit_plugin_source(plugin_name):
    """插件源码/配置在线编辑(编辑插件目录下实际存在的文本文件,
    realpath 校验 + 自动备份 + 语法检查)"""
    try:
        plugin_dir = os.path.realpath(os.path.join("plugins", plugin_name))
        plugins_root = os.path.realpath("plugins")
        if not plugin_dir.startswith(plugins_root + os.sep) or \
                not os.path.exists(os.path.join(plugin_dir, "package.json")):
            return jsonify({'success': False, 'message': '插件不存在'})

        # 可编辑的文本文件扩展名(其余类型一律拒绝)
        EDITABLE_EXTS = ('.py', '.json', '.md', '.txt', '.ini', '.yaml', '.yml',
                         '.toml', '.cfg', '.conf', '.csv', '.html', '.css', '.js', '.sh')
        # 运行时/二进制文件不提供编辑
        EXCLUDE_NAMES = {'cache.json', 'plugin.log'}
        EXCLUDE_EXTS = ('.db', '.log', '.pyc', '.zip', '.png', '.jpg', '.jpeg',
                        '.gif', '.sqlite', '.sqlite3')

        def _is_editable(rel_path):
            """判断插件目录内的相对路径是否为可编辑文本文件"""
            rel_path = rel_path.replace('\\', '/')
            if rel_path.startswith('/') or '..' in rel_path.split('/'):
                return False
            name = os.path.basename(rel_path)
            if name in EXCLUDE_NAMES or name.startswith('.'):
                return False
            ext = os.path.splitext(name)[1].lower()
            if ext in EXCLUDE_EXTS:
                return False
            return ext in EDITABLE_EXTS

        def _safe_resolve(rel_path):
            """相对路径安全解析到插件目录内; 越界/非法返回 None"""
            abs_path = os.path.realpath(os.path.join(plugin_dir, rel_path))
            if not abs_path.startswith(plugin_dir + os.sep):
                return None
            return abs_path

        if request.method == 'GET':
            # 返回插件目录下所有可编辑的文本文件(相对路径 -> 内容)
            files = {}
            skipped = []
            for root, dirs, fnames in os.walk(plugin_dir):
                # 跳过缓存目录
                dirs[:] = [d for d in dirs if d not in ('__pycache__',)]
                for fname in fnames:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, plugin_dir)
                    if not _is_editable(rel):
                        continue
                    try:
                        if os.path.getsize(full) > 256 * 1024:
                            skipped.append(rel)
                            continue
                        with open(full, 'r', encoding='utf-8', errors='replace') as f:
                            files[rel.replace(os.sep, '/')] = f.read()
                    except OSError:
                        continue
            return jsonify({'success': True, 'files': files, 'skipped': skipped})

        # POST 保存
        data = request.json
        file = (data.get('file', '') or '').replace('\\', '/')
        content = data.get('content', '')

        if not _is_editable(file):
            return jsonify({'success': False, 'message': '不允许编辑该文件'})

        fpath = _safe_resolve(file)
        if fpath is None:
            return jsonify({'success': False, 'message': '非法文件路径'})

        # 自动备份当前版本
        plugin_manager.backup_plugin(plugin_name)

        # 按文件类型校验(只校验新内容, 不执行)
        if file.endswith('.py'):
            import py_compile
            try:
                check_path = fpath + ".check"
                with open(check_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                try:
                    py_compile.compile(check_path, doraise=True)
                finally:
                    try:
                        os.remove(check_path)
                    except OSError:
                        pass
            except py_compile.PyCompileError as e:
                return jsonify({'success': False,
                                'message': f'语法错误: {e.msg}' if hasattr(e, 'msg') else f'语法错误: {str(e)}'})
        elif file.endswith('.json'):
            if content.strip():
                try:
                    json.loads(content)
                except ValueError as e:
                    return jsonify({'success': False, 'message': f'JSON 格式错误: {str(e)}'})

        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)

        # 通知机器人重载该插件
        get_bridge().send_command('reload', plugin_name, wait=True)
        log_handler.add_log(f"编辑插件文件: {plugin_name}/{file}")
        return jsonify({'success': True, 'message': f'{file} 已保存并重载'})

    except Exception as e:
        log_handler.add_log(f"编辑插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'编辑失败: {str(e)}'})

@app.route('/api/plugins/logs')
@login_required
def plugin_logs():
    """插件日志(plugin.log 尾行 + 机器人运行日志中相关行)"""
    try:
        plugin_name = request.args.get('plugin_name', '')
        if not plugin_name:
            return jsonify({'success': False, 'message': '缺少插件名'})

        file_logs = []
        log_path = os.path.join("plugins", plugin_name, "plugin.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    file_logs = f.readlines()[-200:]
            except OSError:
                pass

        # 从机器人运行日志 grep 相关行(尾 200 行)
        bot_logs = []
        try:
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    all_lines = f.readlines()
                matching = [ln for ln in all_lines
                            if plugin_name in ln or f"[{plugin_name}]" in ln]
                bot_logs = matching[-200:]
        except OSError:
            pass

        return jsonify({'success': True,
                        'file_logs': [ln.rstrip('\n') for ln in file_logs],
                        'bot_logs': [ln.rstrip('\n') for ln in bot_logs]})

    except Exception as e:
        log_handler.add_log(f"获取插件日志失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/api/<plugin_name>/<path:path>', methods=['GET', 'POST'])
@login_required
def plugin_api_proxy(plugin_name, path):
    """代理请求到机器人进程内的插件 API 服务"""
    try:
        body = None
        if request.method == 'POST':
            body = request.get_json(silent=True) or {}
        # 保留原始查询字符串，否则 GET 参数(如 target/pn/ps)会被丢弃
        query = request.query_string.decode('utf-8', 'ignore')
        full_path = '/' + path + (('?' + query) if query else '')
        status_code, result = get_bridge().proxy_api(
            plugin_name, full_path, request.method, body)
        if isinstance(result, dict):
            return jsonify(result), status_code
        return jsonify({'success': True, 'data': result}), status_code
    except Exception as e:
        log_handler.add_log(f"插件API代理失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'代理失败: {str(e)}'}), 502

@app.route('/api/plugins/metrics')
@login_required
def plugin_metrics():
    """插件指标与仪表盘数据(经桥接从机器人进程获取)"""
    try:
        plugin_filter = request.args.get('plugin', '')
        path = '/metrics'
        if plugin_filter:
            path += f'?plugin={plugin_filter}'
        status_code, result = get_bridge().proxy_api(None, path)
        if isinstance(result, dict):
            return jsonify(result), status_code
        return jsonify({'success': True, 'data': result}), status_code
    except Exception as e:
        log_handler.add_log(f"获取插件指标失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/plugins/toggle', methods=['POST'])
@login_required
def toggle_plugin():
    """启用/禁用插件(面板写 package.json, 经桥接命令通知机器人)"""
    try:
        data = request.json
        plugin_name = data.get('plugin_name')
        enabled = data.get('enabled')

        if not plugin_name:
            return jsonify({'success': False, 'message': '插件名称不能为空'})

        # 面板写 package.json 的 enabled 字段
        if not plugin_manager.set_plugin_enabled(plugin_name, enabled):
            return jsonify({'success': False, 'message': '更新插件启用状态失败'})

        action = "启用" if enabled else "禁用"
        # 通知机器人进程执行(enable 时机器人按 package.json 现状加载)
        result = get_bridge().send_command('enable' if enabled else 'disable',
                                           plugin_name, wait=True)
        log_handler.add_log(f"{action}插件: {plugin_name}")

        if result.get('bot_running'):
            if result.get('executed') and result.get('result', {}).get('success'):
                return jsonify({'success': True, 'message': f'插件已{action}',
                                'enabled': enabled})
            return jsonify({'success': True,
                            'message': f'插件已{action}(机器人执行结果: {result.get("message", "未知")})',
                            'enabled': enabled})
        return jsonify({'success': True,
                        'message': f'插件已{action}(机器人未运行，将在下次启动时生效)',
                        'enabled': enabled, 'bot_not_running': True})

    except Exception as e:
        log_handler.add_log(f"切换插件状态失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'操作失败: {str(e)}'})
    
# GitHub OAuth 配置
GITHUB_CLIENT_ID = panel_config.get_github_config().get("client_id", "")
GITHUB_CLIENT_SECRET = panel_config.get_github_config().get("client_secret", "")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

@app.route('/github/login')
@login_required
def github_login():
    """GitHub OAuth 登录"""
    # 生成随机的state参数防止CSRF攻击
    state = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    session['github_oauth_state'] = state
    
    params = {
        'client_id': GITHUB_CLIENT_ID,
        'redirect_uri': url_for("github_callback", _external=True),
        'scope': 'public_repo,read:user',
        'state': state,
        'allow_signup': 'true'
    }
    
    auth_url = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    return redirect(auth_url)

@app.route('/github/callback')
@login_required
def github_callback():
    """GitHub OAuth 回调"""
    code = request.args.get('code')
    state = request.args.get('state')
    stored_state = session.get('github_oauth_state')
    
    if not code:
        log_handler.add_log("GitHub授权失败: 未收到授权码", "ERROR")
        return redirect(url_for('index') + '?error=GitHub授权失败: 未收到授权码#github_discussions')
    
    if state != stored_state:
        log_handler.add_log("GitHub授权失败: State参数不匹配", "ERROR")
        return redirect(url_for('index') + '?error=GitHub授权失败: State参数不匹配#github_discussions')
    
    # 清理session中的state
    session.pop('github_oauth_state', None)
    
    try:
        # 交换access token - 使用正确的格式
        token_data = {
            'client_id': GITHUB_CLIENT_ID,
            'client_secret': GITHUB_CLIENT_SECRET,
            'code': code,
            'redirect_uri': url_for('github_callback', _external=True)
        }
        
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # 使用 data 参数而不是 json，并添加正确的 Content-Type
        response = requests.post(
            GITHUB_TOKEN_URL, 
            data=token_data,  # 改为 data 而不是 json
            headers={'Accept': 'application/json'}  # 只保留这个header
        )
        
        # 检查响应状态
        if response.status_code != 200:
            error_detail = f"HTTP {response.status_code}: {response.text}"
            log_handler.add_log(f"GitHub token交换失败: {error_detail}", "ERROR")
            return redirect(url_for('index') + f'?error=GitHub授权失败: {error_detail}#github_discussions')
        
        token_info = response.json()
        access_token = token_info.get('access_token')
        
        if not access_token:
            error_msg = token_info.get('error_description', '未知错误')
            log_handler.add_log(f"GitHub授权失败: {error_msg}", "ERROR")
            return redirect(url_for('index') + f'?error=GitHub授权失败: {error_msg}#github_discussions')
        
        # 保存access token到配置
        panel_config.update_github_token(access_token)
        
        # 重新初始化GitHub客户端
        github_manager._init_github_client()
        
        log_handler.add_log("GitHub登录成功")
        return redirect(url_for('index') + '#github_discussions')
    
    except Exception as e:
        log_handler.add_log(f"GitHub授权失败: {str(e)}", "ERROR")
        return redirect(url_for('index') + f'?error=GitHub授权失败: {str(e)}#github_discussions')

@app.route('/github/logout')
@login_required
def github_logout():
    """GitHub 退出登录 - 清除本地令牌并调用 GitHub API 撤销访问"""
    try:
        # 获取当前的 GitHub 配置
        github_config = panel_config.get_github_config()
        access_token = github_config.get('access_token', '')
        
        # 如果有访问令牌，先调用 GitHub API 撤销它
        if access_token:
            try:
                # GitHub OAuth 应用撤销令牌的 URL
                revoke_url = "https://api.github.com/applications/{client_id}/token"
                
                # 获取客户端 ID 和密钥
                client_id = github_config.get('client_id', '')
                client_secret = github_config.get('client_secret', '')
                
                if client_id and client_secret:
                    # 使用 Basic Auth 调用 GitHub API 撤销令牌
                    auth = (client_id, client_secret)
                    data = {'access_token': access_token}
                    
                    response = requests.delete(
                        revoke_url.format(client_id=client_id),
                        auth=auth,
                        json=data,
                        timeout=10
                    )
                    
                    if response.status_code == 204:
                        log_handler.add_log("GitHub 访问令牌已成功撤销")
                    else:
                        log_handler.add_log(f"GitHub 令牌撤销 API 返回状态码: {response.status_code}", "WARNING")
                else:
                    log_handler.add_log("GitHub 客户端 ID 或密钥未配置，无法调用撤销 API", "WARNING")
                    
            except Exception as api_error:
                log_handler.add_log(f"调用 GitHub 撤销 API 失败: {str(api_error)}", "WARNING")
                # 即使撤销 API 调用失败，仍然继续本地退出流程
        
        # 清除本地存储的访问令牌（保留其他配置）
        panel_config.update_github_config(
            client_id=github_config.get('client_id', ''),
            client_secret=github_config.get('client_secret', ''),
            access_token="",  # 清空访问令牌
            repo_owner=github_config.get('repo_owner', '7Hello80'),
            repo_name=github_config.get('repo_name', 'Bilibili_PrivateMessage_Bot')
        )
        
        # 重新初始化 GitHub 客户端
        github_manager._init_github_client()
        
        log_handler.add_log("GitHub 退出登录完成")
        
        return redirect(url_for('index') + '#github_discussions')
    
    except Exception as e:
        log_handler.add_log(f"GitHub 退出登录失败: {str(e)}", "ERROR")
        return redirect(url_for('index') + f'?error=GitHub退出登录失败: {str(e)}#github_discussions')

# GitHub讨论区API路由
@app.route('/api/github/discussions')
@login_required
def get_github_discussions():
    """获取GitHub讨论列表"""
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)
        state = request.args.get('state', 'open')
        
        result = github_manager.get_discussions(state=state, limit=limit)
        return jsonify(result)
    except Exception as e:
        log_handler.add_log(f"获取GitHub讨论列表失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取讨论列表失败: {str(e)}'})

@app.route('/api/github/discussions/<int:discussion_number>')
@login_required
def get_github_discussion(discussion_number):
    """获取单个GitHub讨论详情"""
    try:
        result = github_manager.get_discussion(discussion_number)
        return jsonify(result)
    except Exception as e:
        log_handler.add_log(f"获取GitHub讨论详情失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取讨论详情失败: {str(e)}'})

@app.route('/api/github/discussions', methods=['POST'])
@login_required
def create_github_discussion():
    """创建新的GitHub讨论"""
    try:
        data = request.json
        title = data.get('title')
        body = data.get('body')
        labels = data.get('labels', [])
        
        if not title or not body:
            return jsonify({'success': False, 'message': '标题和内容不能为空'})
        
        result = github_manager.create_discussion(title, body, labels)
        return jsonify(result)
    except Exception as e:
        log_handler.add_log(f"创建GitHub讨论失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'创建讨论失败: {str(e)}'})

@app.route('/api/github/discussions/<int:discussion_number>/comments', methods=['POST'])
@login_required
def create_github_comment(discussion_number):
    """在GitHub讨论中发布评论"""
    try:
        data = request.json
        body = data.get('body')
        
        if not body:
            return jsonify({'success': False, 'message': '评论内容不能为空'})
        
        result = github_manager.create_comment(discussion_number, body)
        return jsonify(result)
    except Exception as e:
        log_handler.add_log(f"发布GitHub评论失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'发布评论失败: {str(e)}'})

@app.route('/api/github/user')
@login_required
def get_github_user():
    """获取当前GitHub用户信息"""
    try:
        result = github_manager.get_user_info()
        return jsonify(result)
    except Exception as e:
        log_handler.add_log(f"获取GitHub用户信息失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取用户信息失败: {str(e)}'})

@app.route('/api/github/config', methods=['GET', 'POST'])
@login_required
def github_config():
    """GitHub配置管理"""
    if request.method == 'GET':
        
        github_config = panel_config.get_github_config()
        # 不返回client_secret
        safe_config = {
            'client_id': github_config.get('client_id', ''),
            'repo_owner': github_config.get('repo_owner', '7Hello80'),
            'repo_name': github_config.get('repo_name', 'Bilibili_PrivateMessage_Bot'),
            'is_authenticated': github_manager.is_authenticated()
        }
        return jsonify({'success': True, 'config': safe_config})
    
    else:  # POST
        try:
            data = request.json
            client_id = data.get('client_id')
            client_secret = data.get('client_secret')
            repo_owner = data.get('repo_owner')
            repo_name = data.get('repo_name')
            
            panel_config.update_github_config(client_id, client_secret, "", repo_owner, repo_name)
            
            # 更新全局变量
            global GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
            GITHUB_CLIENT_ID = client_id
            GITHUB_CLIENT_SECRET = client_secret
            
            log_handler.add_log("GitHub配置已更新")
            return jsonify({'success': True, 'message': 'GitHub配置更新成功'})
        except Exception as e:
            log_handler.add_log(f"更新GitHub配置失败: {str(e)}", "ERROR")
            return jsonify({'success': False, 'message': f'更新配置失败: {str(e)}'})

@app.route('/api/plugins/reload', methods=['POST'])
@login_required
def reload_plugin():
    """重新加载插件(经桥接命令通知机器人)"""
    try:
        plugin_name = request.json.get('plugin_name')
        result = get_bridge().send_command('reload', plugin_name, wait=True)
        log_handler.add_log(f"重新加载插件: {plugin_name}")
        if result.get('bot_running'):
            return jsonify({'success': result.get('executed', False),
                            'message': result.get('message', '已下发重载命令')})
        return jsonify({'success': True,
                        'message': '机器人未运行，将在下次启动时按最新文件加载',
                        'bot_not_running': True})

    except Exception as e:
        log_handler.add_log(f"重新加载插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'重新加载失败: {str(e)}'})

@app.route('/api/plugins/create', methods=['POST'])
@login_required
def create_plugin():
    """创建新插件"""
    try:
        data = request.json
        plugin_name = data.get('name')
        plugin_type = data.get('type', 'base')
        author = data.get('author', '匿名')
        description = data.get('description', '')
        version = data.get('version', '1.0.0')
        
        if plugin_creator.create_plugin(plugin_name, plugin_type, author, description, version):
            log_handler.add_log(f"创建插件: {plugin_name}")
            return jsonify({'success': True, 'message': '插件创建成功'})
        else:
            return jsonify({'success': False, 'message': '插件创建失败'})
    
    except Exception as e:
        log_handler.add_log(f"创建插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'创建失败: {str(e)}'})

# 添加系统监控数据获取函数
def get_system_stats():
    """获取系统状态信息。

    Android/Termux 下 /proc/stat、/proc/net/dev、/proc/loadavg 等文件通常
    被 SELinux 限制为不可读，psutil 会抛出 PermissionError。此时相关指标
    返回 None，由前端显示“不可用”，而不是把“读不到”误报成 0（用户会
    误以为设备真的空闲）。内存 /proc/meminfo 与磁盘配额一般可读，仍正常返回。
    """
    # ---------- CPU ----------
    cpu_count = None
    cpu_count_logical = None
    try:
        cpu_count = psutil.cpu_count(logical=False)          # 物理核心
        cpu_count_logical = psutil.cpu_count(logical=True)   # 逻辑核心
    except Exception:
        cpu_count = None
        cpu_count_logical = None
    if not cpu_count_logical:
        cpu_count_logical = os.cpu_count()
    if not cpu_count:
        cpu_count = cpu_count_logical

    cpu_percent = None
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)       # CPU 使用率
    except Exception:
        cpu_percent = None

    # 系统负载（部分平台同时缺失 psutil/os 版本，逐级降级）
    load_avg = None
    if platform.system() != 'Windows':
        try:
            load_avg = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            try:
                load_avg = [round(x, 2) for x in psutil.getloadavg()]
            except Exception:
                load_avg = None

    # CPU 使用率来源：psutil 直接读取 > 系统负载换算 > 不可用
    cpu_usage_source = None
    if cpu_percent is not None:
        cpu_usage_source = 'psutil'
    elif load_avg:
        cores = cpu_count_logical or cpu_count or 1
        cpu_percent = max(0.0, min(100.0, load_avg[0] / cores * 100))
        cpu_usage_source = 'loadavg'
    if cpu_percent is not None:
        cpu_percent = round(float(cpu_percent), 1)

    # ---------- 内存 ----------
    mem_total = mem_used = mem_percent = None
    try:
        mem = psutil.virtual_memory()
        mem_total = mem.total / (1024 ** 3)   # 总内存(GB)
        mem_used = mem.used / (1024 ** 3)     # 已用内存(GB)
        mem_percent = mem.percent             # 内存使用率
    except Exception:
        mem_total = mem_used = mem_percent = None

    # ---------- 磁盘 ----------
    disk_total = disk_used = disk_percent = None
    try:
        disk = psutil.disk_usage(disk_default)
        disk_total = disk.total / (1024 ** 3)  # 总磁盘空间(GB)
        disk_used = disk.used / (1024 ** 3)    # 已用磁盘空间(GB)
        disk_percent = disk.percent            # 磁盘使用率
    except Exception:
        disk_total = disk_used = disk_percent = None

    # ---------- 网络 IO ----------
    net_bytes_sent = net_bytes_recv = None
    net_packets_sent = net_packets_recv = None
    net_errin = net_errout = net_dropin = net_dropout = None
    sent_speed = recv_speed = None
    net_io = None
    try:
        net_io = psutil.net_io_counters()
    except Exception:
        net_io = None

    if net_io is not None:
        net_bytes_sent = net_io.bytes_sent / (1024 ** 2)  # 发送数据量(MB)
        net_bytes_recv = net_io.bytes_recv / (1024 ** 2)  # 接收数据量(MB)
        net_packets_sent = net_io.packets_sent            # 发送包数量
        net_packets_recv = net_io.packets_recv            # 接收包数量
        net_errin = net_io.errin                          # 接收错误数
        net_errout = net_io.errout                        # 发送错误数
        net_dropin = net_io.dropin                        # 接收丢弃数
        net_dropout = net_io.dropout                      # 发送丢弃数

        # 计算网络速度（需要保存上一次的数据）
        current_time = time.time()
        last_net = getattr(get_system_stats, 'last_net_io', None)
        if last_net is None:
            # 第一次调用，只记录基线
            sent_speed = recv_speed = 0.0
        else:
            time_diff = current_time - getattr(get_system_stats, 'last_net_time', current_time)
            if time_diff > 0:
                # 计算速度 (KB/s)，计数器回绕时结果为负，按 0 处理
                sent_speed = max(0.0, (net_io.bytes_sent - last_net.bytes_sent) / time_diff / 1024)
                recv_speed = max(0.0, (net_io.bytes_recv - last_net.bytes_recv) / time_diff / 1024)
            else:
                sent_speed = recv_speed = 0.0
        get_system_stats.last_net_io = net_io
        get_system_stats.last_net_time = current_time

    # 系统信息
    system_info = {
        'os': platform.system(),
        'release': platform.release(),
        'version': platform.version(),
        'processor': platform.processor()
    }

    def _round(value, digits):
        return None if value is None else round(float(value), digits)

    return {
        'cpu': {
            'physical_cores': cpu_count,
            'logical_cores': cpu_count_logical,
            'usage': cpu_percent,               # None 表示当前平台不可读
            'usage_source': cpu_usage_source,   # psutil / loadavg / None
        },
        'memory': {
            'total': _round(mem_total, 2),
            'used': _round(mem_used, 2),
            'usage': _round(mem_percent, 1),
        },
        'disk': {
            'total': _round(disk_total, 2),
            'used': _round(disk_used, 2),
            'usage': _round(disk_percent, 1),
        },
        'network': {
            'available': net_io is not None,
            'bytes_sent': _round(net_bytes_sent, 2),
            'bytes_recv': _round(net_bytes_recv, 2),
            'packets_sent': net_packets_sent,
            'packets_recv': net_packets_recv,
            'errors_in': net_errin,
            'errors_out': net_errout,
            'drops_in': net_dropin,
            'drops_out': net_dropout,
            'sent_speed': _round(sent_speed, 2),  # 上传速度 KB/s
            'recv_speed': _round(recv_speed, 2),  # 下载速度 KB/s
        },
        'load_avg': load_avg,
        'system': system_info,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


@app.route('/api/proxy_image')
@login_required
def proxy_image():
    """增强版图片代理，解决防盗链问题"""
    image_url = request.args.get('url')
    if not image_url:
        return "Missing URL", 400
    
    try:
        # 设置各种请求头，模拟正常浏览器访问
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",  # 避免压缩，我们需要原始数据
            "Cache-Control": "no-cache"
        }
        
        response = requests.get(image_url, headers=headers, timeout=10, stream=True)
        response.raise_for_status()
        
        # 确定内容类型
        content_type = response.headers.get('content-type', 'image/jpeg')
        
        # 返回图片数据
        return Response(
            response.iter_content(chunk_size=8192),
            content_type=content_type,
            headers={
                'Cache-Control': 'public, max-age=86400',  # 缓存24小时
                'Access-Control-Allow-Origin': '*',  # 允许跨域
                'Content-Disposition': 'inline'  # 内联显示
            }
        )
        
    except requests.exceptions.RequestException as e:
        log_handler.add_log(f"图片代理请求失败: {str(e)}", "ERROR")
        return "Image request failed", 502
    except Exception as e:
        log_handler.add_log(f"图片代理内部错误: {str(e)}", "ERROR")
        return "Internal server error" + e, 500

# 添加系统监控API路由
@app.route('/api/system_stats')
@login_required
def system_stats():
    """获取系统状态数据"""
    try:
        stats = get_system_stats()
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        log_handler.add_log(f"获取系统状态失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'获取失败: {str(e)}'})

@app.route('/api/restart_bot', methods=['POST'])
@login_required
def restart_bot():
    """重启机器人"""
    global bot_process, is_bot_running
    
    try:
        # 先停止机器人
        if is_bot_running and bot_process:
            bot_process.terminate()
            try:
                bot_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bot_process.kill()
                bot_process.wait()
            is_bot_running = False
        
        # 等待一下确保进程完全停止
        time.sleep(2)
        
        # 再启动机器人
        python_path = get_python3_path()
        if not python_path:
            log_handler.add_log("未找到python3解释器", "ERROR")
            return jsonify({'success': False, 'message': '未找到python3解释器'})
        
        bot_process = subprocess.Popen(
            [python_path, 'index.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            bufsize=1
        )
        
        # 启动日志读取线程
        threading.Thread(target=read_bot_output, daemon=True).start()
        
        is_bot_running = True
        log_handler.add_log("机器人重启成功")
        
        return jsonify({'success': True, 'message': '机器人重启成功'})
    
    except Exception as e:
        log_handler.add_log(f"机器人重启失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'重启失败: {str(e)}'})

def read_bot_output():
    """读取机器人输出"""
    global bot_process
    if bot_process and bot_process.stdout:
        for line in iter(bot_process.stdout.readline, ''):
            if line:
                log_handler.add_log(f"BOT: {line.strip()}")

@app.route('/api/get_logs')
@login_required
def get_logs():
    """获取日志"""
    limit = request.args.get('limit', 100, type=int)
    logs = log_handler.get_logs(limit)
    return jsonify({'logs': logs})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
def clear_logs():
    """清除所有日志"""
    try:
        if log_handler.clear_logs():
            log_handler.add_log("管理员清除了所有日志", "INFO")
            return jsonify({'success': True, 'message': '日志清除成功'})
        else:
            return jsonify({'success': False, 'message': '日志清除失败'})
    
    except Exception as e:
        log_handler.add_log(f"日志清除失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'清除失败: {str(e)}'})

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

@app.route('/api/github/discussions/<int:discussion_number>/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_github_comment(discussion_number, comment_id):
    """删除GitHub评论（只能删除自己的评论）"""
    try:
        if not github_manager.is_authenticated():
            return jsonify({'success': False, 'message': 'GitHub未认证'})
        
        # 获取当前用户信息
        user_info = github_manager.get_user_info()
        if not user_info['success']:
            return jsonify({'success': False, 'message': '获取用户信息失败'})
        
        current_user = user_info['user']['login']
        
        # 获取评论信息以验证所有者
        try:
            issue = github_manager.repo.get_issue(discussion_number)
            comment = issue.get_comment(comment_id)
            
            # 检查评论是否属于当前用户
            if comment.user.login != current_user:
                return jsonify({
                    'success': False, 
                    'message': '只能删除自己的评论'
                })
            
            # 删除评论
            comment.delete()
            
            log_handler.add_log(f"删除GitHub评论: #{discussion_number}/#{comment_id}")
            return jsonify({
                'success': True, 
                'message': '评论删除成功'
            })
            
        except github.GithubException as e:
            if e.status == 404:
                return jsonify({'success': False, 'message': '评论不存在'})
            elif e.status == 403:
                return jsonify({'success': False, 'message': '没有删除权限'})
            else:
                raise e
                
    except Exception as e:
        log_handler.add_log(f"删除GitHub评论失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'删除评论失败: {str(e)}'})

# 创建模板目录和文件
def create_templates():
    """确保模板目录存在。

    注意：历史版本会在此函数中把 base/login/error/index 四个模板重新写回磁盘，
    导致任何界面自定义都在每次启动时被旧版页面覆盖（本次 Aurora 改版即受此影响）。
    现改为仅创建目录，模板一律以仓库中的文件为准。
    """
    templates_dir = 'templates'
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        try:
            log_handler.add_log("未找到 templates 目录，已自动创建，请从仓库恢复模板文件", "ERROR")
        except Exception:
            print("未找到 templates 目录，已自动创建，请从仓库恢复模板文件")

    

if __name__ == '__main__':
    # 创建模板文件
    create_templates()
    
    # 启动Flask应用
    print(f"{Fore.GREEN}访问地址: http://127.0.0.1:5000")
    print(f"{Fore.GREEN}默认账号: admin")
    print(f"{Fore.GREEN}默认密码: admin123")
    print(f"{Fore.GREEN}请及时修改默认密码！")
    
    # 关闭调试模式，避免重启
    app.run(debug=False, host='0.0.0.0', port=5000)
