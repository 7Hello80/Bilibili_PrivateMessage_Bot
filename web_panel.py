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

# 导入现有的配置管理
import ConfigManage

CURRENT_VERSION = "MS4xLjM="
UPDATE_CHECK_URL = "aHR0cDovLzExNC4xMzQuMTg4LjE4OD9pZD0x"
Version = "2.0.4"
system_name = platform.system()
system_version = platform.version()
disk_default = "/mnt"

if system_name == "Linux":
    #获取linux发行版名称
    system_distribution = distro.name()
else:
    system_distribution = system_name + " " + platform.release()

init.init_manage()

app = Flask(__name__)
app.secret_key = 'AepOrtcOteq18763HHytqxj!jsb586uqsh'

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
    """安装插件(面板进程不执行插件代码, 通过桥接命令让机器人热加载)"""
    try:
        data = request.json
        repo_full_name = data.get('repo_full_name')
        plugin_name = data.get('plugin_name')

        result = plugin_manager.download_plugin(repo_full_name, plugin_name)

        if result:
            # 通知机器人进程热加载新插件
            bridge_result = get_bridge().send_command('load', plugin_name, wait=True)
            log_handler.add_log(f"安装插件: {plugin_name}")
            msg = '插件安装成功'
            if bridge_result.get('bot_running'):
                msg = f"{msg}，已通知机器人加载"
            else:
                msg = f"{msg}(机器人未运行，将在下次启动时加载)"
            return jsonify({'success': True, 'message': msg,
                            'bot_not_running': not bridge_result.get('bot_running', True)})
        else:
            return jsonify({'success': False, 'message': '插件安装失败(下载或校验未通过)'})

    except Exception as e:
        log_handler.add_log(f"安装插件失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'message': f'安装失败: {str(e)}'})

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
        status_code, result = get_bridge().proxy_api(
            plugin_name, '/' + path, request.method, body)
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
    """获取系统状态信息"""
    # CPU信息
    cpu_count = psutil.cpu_count(logical=False)  # 物理核心
    cpu_count_logical = psutil.cpu_count(logical=True)  # 逻辑核心
    cpu_percent = psutil.cpu_percent(interval=0.1)  # CPU使用率
    
    # 内存信息
    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024 **3)  # 总内存(GB)
    mem_used = mem.used / (1024** 3)    # 已用内存(GB)
    mem_percent = mem.percent           # 内存使用率
    
    # 磁盘信息
    disk = psutil.disk_usage(disk_default)
    disk_total = disk.total / (1024 **3)  # 总磁盘空间(GB)
    disk_used = disk.used / (1024** 3)    # 已用磁盘空间(GB)
    disk_percent = disk.percent           # 磁盘使用率

    # 网络IO信息
    net_io = psutil.net_io_counters()
    net_bytes_sent = net_io.bytes_sent / (1024 ** 2)  # 发送数据量(MB)
    net_bytes_recv = net_io.bytes_recv / (1024 ** 2)  # 接收数据量(MB)
    net_packets_sent = net_io.packets_sent            # 发送包数量
    net_packets_recv = net_io.packets_recv            # 接收包数量
    net_errin = net_io.errin                          # 接收错误数
    net_errout = net_io.errout                        # 发送错误数
    net_dropin = net_io.dropin                        # 接收丢弃数
    net_dropout = net_io.dropout 
    
    # 计算网络速度（需要保存上一次的数据）
    current_time = time.time()
    if not hasattr(get_system_stats, 'last_net_io'):
        # 第一次调用，初始化数据
        get_system_stats.last_net_io = net_io
        get_system_stats.last_net_time = current_time
        sent_speed = 0
        recv_speed = 0
    else:
        # 计算时间差
        time_diff = current_time - get_system_stats.last_net_time
        if time_diff > 0:
            # 计算速度 (KB/s)
            sent_speed = (net_io.bytes_sent - get_system_stats.last_net_io.bytes_sent) / time_diff / 1024
            recv_speed = (net_io.bytes_recv - get_system_stats.last_net_io.bytes_recv) / time_diff / 1024
        else:
            sent_speed = 0
            recv_speed = 0
        
        # 更新上一次的数据
        get_system_stats.last_net_io = net_io
        get_system_stats.last_net_time = current_time

    # 系统负载
    load_avg = None
    if platform.system() != 'Windows':
        try:
            load = psutil.getloadavg()
            load_avg = [round(x, 2) for x in load]
        except AttributeError:
            pass
    
    # 系统信息
    system_info = {
        'os': platform.system(),
        'release': platform.release(),
        'version': platform.version(),
        'processor': platform.processor()
    }
    
    return {
        'cpu': {
            'physical_cores': cpu_count,
            'logical_cores': cpu_count_logical,
            'usage': cpu_percent
        },
        'memory': {
            'total': round(mem_total, 2),
            'used': round(mem_used, 2),
            'usage': mem_percent
        },
        'disk': {
            'total': round(disk_total, 2),
            'used': round(disk_used, 2),
            'usage': disk_percent
        },
        'network': {
            'bytes_sent': round(net_bytes_sent, 2),
            'bytes_recv': round(net_bytes_recv, 2),
            'packets_sent': net_packets_sent,
            'packets_recv': net_packets_recv,
            'errors_in': net_errin,
            'errors_out': net_errout,
            'drops_in': net_dropin,
            'drops_out': net_dropout,
            'sent_speed': round(sent_speed, 2),  # 上传速度 KB/s
            'recv_speed': round(recv_speed, 2)   # 下载速度 KB/s
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
    """创建HTML模板文件"""
    templates_dir = 'templates'
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    # 创建错误页面
    with open(os.path.join(templates_dir, 'error.html'), 'w', encoding='utf-8') as f:
        f.write('''{% extends "base.html" %}

{% block content %}
<div class="min-h-screen bg-gray-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
        <div class="bg-white py-8 px-6 shadow rounded-xl sm:px-10 border border-gray-100">
            <!-- 错误图标 -->
            <div class="text-center mb-8">
                <div class="mx-auto flex items-center justify-center h-16 w-16 rounded-full bg-red-100">
                    <i class="fa fa-exclamation-triangle text-red-600 text-2xl"></i>
                </div>
                <h2 class="mt-4 text-3xl font-bold text-gray-900">
                    发生错误
                </h2>
            </div>

            <!-- 错误信息 -->
            <div class="text-center">
                <p class="text-lg text-gray-600 mb-6">
                    {{ error }}
                </p>
                
                <!-- 操作按钮 -->
                <div class="space-y-4">
                    <a href="/" class="w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition">
                        <i class="fa fa-home mr-2"></i>返回首页
                    </a>
                    
                    <button onclick="history.back()" class="w-full flex justify-center py-3 px-4 border border-gray-300 text-sm font-medium rounded-lg text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 transition">
                        <i class="fa fa-arrow-left mr-2"></i>返回上页
                    </button>
                </div>
                
                <!-- 技术支持 -->
                <div class="mt-6 pt-6 border-t border-gray-200">
                    <p class="text-sm text-gray-500">
                        如果问题持续存在，请联系技术支持
                    </p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}''')
    
    # 创建基础模板
    with open(os.path.join(templates_dir, 'base.html'), 'w', encoding='utf-8') as f:
        f.write('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="renderer" content="webkit">
    <meta name="format-detection" content="telephone=no">
    <meta name="spm_prefix" content="333.40164">
    <title>{% block title %}B站私信机器人控制面板{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/typescript.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/java.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/cpp.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/csharp.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/php.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/ruby.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/go.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/rust.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/sql.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/swift.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/kotlin.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/scala.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/dart.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/r.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/matlab.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/perl.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/lua.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/haskell.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/elixir.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/clojure.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/erlang.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/fortran.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/vbnet.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/objectivec.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/dockerfile.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/nginx.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/apache.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/makefile.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/cmake.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/gradle.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/groovy.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/powershell.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/shell.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/vim.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/ini.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/markdown.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/latex.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/diff.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/plaintext.min.js"></script>
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
    <!-- 引入 layui.css -->
    <link href="//unpkg.com/layui@2.12.1/dist/css/layui.css" rel="stylesheet">
    <!-- 引入 layui.js -->
    <script src="//unpkg.com/layui@2.12.1/dist/layui.js"></script>
    <script src="https://testingcf.jsdelivr.net/npm/chart.js"></script>
    <!-- 在 base.html 的 head 部分添加 -->
    <script src="https://testingcf.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://testingcf.jsdelivr.net/npm/highlightjs-line-numbers.js@2.6.0/dist/highlightjs-line-numbers.min.js"></script>
    <link href="{{ url_for('static', filename='style.css') }}" rel="stylesheet">
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
<div class="min-h-screen bg-gray-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
    <div class="max-w-md w-full space-y-8">
        <div class="bg-white py-8 px-6 shadow rounded-xl sm:px-10 border border-gray-100">
            <!-- 头部 -->
            <div class="text-center mb-8">
                <h2 class="text-3xl font-bold text-gray-900">
                    B站私信机器人
                </h2>
                <p class="mt-2 text-gray-600">
                    控制面板登录
                </p>
            </div>

            <!-- 登录表单 -->
            <form class="space-y-6" method="POST">
                <!-- 错误提示 -->
                {% if error %}
                <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center">
                    <i class="fa fa-exclamation-circle mr-3"></i>
                    <span class="font-medium">{{ error }}</span>
                </div>
                {% endif %}

                <!-- 用户名输入 -->
                <div>
                    <label for="username" class="block text-sm font-medium text-gray-700 mb-2">用户名</label>
                    <div class="mt-1 relative rounded-md shadow-sm">
                        <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                            <i class="fa fa-user text-gray-400"></i>
                        </div>
                        <input id="username" name="username" type="text" required
                               class="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                               placeholder="请输入用户名">
                    </div>
                </div>

                <!-- 密码输入 -->
                <div>
                    <label for="password" class="block text-sm font-medium text-gray-700 mb-2">密码</label>
                    <div class="mt-1 relative rounded-md shadow-sm">
                        <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                            <i class="fa fa-lock text-gray-400"></i>
                        </div>
                        <input id="password" name="password" type="password" required
                               class="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                               placeholder="请输入密码">
                    </div>
                </div>

                <!-- 登录按钮 -->
                <div>
                    <button type="submit"
                            class="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-white bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-all duration-200 shadow-md hover:shadow-lg">
                        <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                            <i class="fa fa-sign-in-alt text-blue-200 group-hover:text-blue-100"></i>
                        </span>
                        登录系统
                    </button>
                </div>
            </form>
        </div>
    </div>
</div>
{% endblock %}''')
    
    # 创建主控制面板
    with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('''{% extends "base.html" %}

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
                    <h1 class="text-lg font-bold text-gray-800">B站私信机器人</h1>
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
            <a href="#accounts" onclick="showSection('accounts')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-users text-gray-400 w-5"></i>
                <span>多账号管理</span>
            </a>
            <a href="#github_discussions" onclick="showSection('github_discussions')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fab fa-github text-gray-400 w-5"></i>
                <span>GitHub讨论区</span>
            </a>
            <a href="#plugins" onclick="showSection('plugins')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-puzzle-piece text-gray-400 w-5"></i>
                <span>插件商店</span>
            </a>
            <a href="#logs" onclick="showSection('logs')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-terminal text-gray-400 w-5"></i>
                <span>运行日志</span>
            </a>
            <a href="#admin" onclick="showSection('admin')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-user-shield text-gray-400 w-5"></i>
                <span>账号设置</span>
            </a>
            <a href="#about" onclick="showSection('about')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-user text-gray-400 w-5"></i>
                <span>关于我们</span>
            </a>
            <a href="#image_bed" onclick="showSection('image_bed')" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fa fa-images text-gray-400 w-5"></i>
                <span>图床管理</span>
            </a>
            <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot" target="_blank" class="nav-item flex items-center space-x-3 px-4 py-3 text-gray-600 hover:bg-gray-50 rounded-lg transition">
                <i class="fab fa-github text-gray-800 w-5"></i>
                <span>GitHub仓库</span>
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
        <!-- GitHub讨论区 -->
        <div id="github_discussions" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center justify-between">
                    <div class="flex items-center">
                        <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                            <i class="fa fa-bars"></i>
                        </button>
                        <div>
                            <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">GitHub讨论区</h2>
                            <p class="text-gray-600 mt-2">参与项目讨论和交流</p>
                        </div>
                    </div>
                    <div class="flex space-x-3">
                        <button onclick="showGitHubConfigModal()" 
                                class="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500 transition flex items-center">
                            <i class="fa fa-cog mr-2"></i>配置
                        </button>
                        <button id="github-login-btn" onclick="githubLogin()" 
                                class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 transition flex items-center hidden">
                            <i class="fab fa-github mr-2"></i>登录GitHub
                        </button>
                        <button id="github-logout-btn" onclick="githubLogout()" 
                                class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 transition flex items-center hidden">
                            <i class="fab fa-github mr-2"></i>退出登录
                        </button>
                        <button onclick="loadDiscussions()" 
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition flex items-center">
                            <i class="fa fa-refresh mr-2"></i>刷新
                        </button>
                    </div>
                </div>
            </div>

            <!-- GitHub用户信息 -->
            <div id="github-user-info" class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6 hidden">
                <div class="flex items-center space-x-4">
                    <img id="github-avatar" src="" alt="GitHub头像" class="w-12 h-12 rounded-full">
                    <div>
                        <h3 class="text-lg font-medium text-gray-800" id="github-username"></h3>
                        <p class="text-gray-600" id="github-display-name"></p>
                    </div>
                </div>
            </div>

            <!-- 讨论列表 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 mb-6">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-medium text-gray-800">讨论列表</h3>
                </div>
                <div id="discussions-list" class="p-6">
                    <div class="text-center text-gray-500 py-8">
                        <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                        <p>加载中...</p>
                    </div>
                </div>
            </div>
        </div>
        <div id="plugins" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">插件商店</h2>
                        <p class="text-gray-600 mt-2">管理和扩展机器人功能</p>
                    </div>
                </div>
            </div>

            <!-- 搜索和操作栏 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
                <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between space-y-4 lg:space-y-0">
                    <div class="flex-1 lg:max-w-md">
                        <div class="relative">
                            <input type="text" id="plugin-search" 
                                class="w-full px-4 py-3 pl-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                placeholder="搜索插件...">
                            <i class="fa fa-search absolute left-3 top-3 text-gray-400"></i>
                        </div>
                    </div>
                    <div class="flex flex-wrap gap-3">
                        <button onclick="showCreatePluginModal()"
                                class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 transition flex items-center">
                            <i class="fa fa-plus mr-2"></i>创建插件
                        </button>
                        <button onclick="document.getElementById('plugin-zip-file').click()"
                                class="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 transition flex items-center">
                            <i class="fa fa-file-archive mr-2"></i>导入ZIP
                        </button>
                        <input type="file" id="plugin-zip-file" accept=".zip" style="display: none;" onchange="importPluginZip(this)">
                        <button onclick="reloadAllPlugins()"
                                class="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 focus:outline-none focus:ring-2 focus:ring-orange-500 transition flex items-center">
                            <i class="fa fa-sync-alt mr-2"></i>全部重载
                        </button>
                        <button onclick="loadInstalledPlugins(); getPluginList()"
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition flex items-center">
                            <i class="fa fa-refresh mr-2"></i>刷新
                        </button>
                    </div>
                </div>
            </div>

            <!-- 已安装插件 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 mb-6">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-medium text-gray-800">已安装插件</h3>
                </div>
                <div id="installed-plugins-list" class="p-6">
                    <div class="text-center text-gray-500 py-8">
                        <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                        <p>加载中...</p>
                    </div>
                </div>
            </div>

            <!-- 在线插件 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-medium text-gray-800">插件市场</h3>
                </div>
                <div id="online-plugins-list" class="p-6">
                    <div class="text-center text-gray-500 py-8">
                        <p>在搜索框中输入关键词搜索插件</p>
                    </div>
                </div>
            </div>
        </div>
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
            
            <!-- 更新提示 -->
            <div id="update-alert" class="hidden bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6">
                <div class="flex items-center">
                    <div class="flex-shrink-0">
                        <i class="fa fa-sync-alt text-blue-400 text-xl"></i>
                    </div>
                    <div class="ml-3 flex-1">
                        <h3 class="text-sm font-medium text-blue-800">
                            发现新版本！
                        </h3>
                        <div class="mt-1 text-sm text-blue-700">
                            <p>当前版本: <span id="current-version" class="font-semibold">v1.0.0</span> → 
                            最新版本: <span id="latest-version" class="font-semibold">v1.0.0</span></p>
                            <p class="mt-1" id="update-announcement">更新内容加载中...</p>
                        </div>
                        <div class="mt-2 flex space-x-2">
                            <a id="update-link" target="_blank" 
                            class="inline-flex items-center px-3 py-1 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition">
                                <i class="fa fa-external-link-alt mr-1"></i>前往更新
                            </a>
                            <button onclick="hideUpdateAlert()" 
                                    class="inline-flex items-center px-3 py-1 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition">
                                <i class="fa fa-times mr-1"></i>忽略
                            </button>
                        </div>
                    </div>
                    <button type="button" onclick="hideUpdateAlert()" class="ml-auto -mx-1.5 -my-1.5 bg-blue-50 text-blue-500 rounded-lg focus:ring-2 focus:ring-blue-400 p-1.5 hover:bg-blue-200 inline-flex h-8 w-8">
                        <span class="sr-only">关闭</span>
                        <i class="fa fa-times"></i>
                    </button>
                </div>
            </div>

            <!-- 状态卡片 -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 lg:gap-6 mb-6">
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
                            <i class="fa fa-users text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">账号总数</h3>
                            <p id="total-accounts-count" class="text-2xl font-semibold text-gray-800">0</p>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 card-hover">
                    <div class="flex items-center">
                        <div class="p-3 rounded-xl bg-purple-100 text-purple-600">
                            <i class="fa fa-play-circle text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">启用账号</h3>
                            <p id="enabled-accounts-count" class="text-2xl font-semibold text-gray-800">0</p>
                        </div>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 card-hover">
                    <div class="flex items-center">
                        <div class="p-3 rounded-xl bg-orange-100 text-orange-600">
                            <i class="fa fa-key text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-sm font-medium text-gray-600">全局关键词</h3>
                            <p id="global-keywords-count" class="text-2xl font-semibold text-gray-800">0</p>
                        </div>
                    </div>
                </div>
            </div>
                
            <div class="bg-write rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
                <h3 class="text-lg font-medium text-gray-800 mb-4">项目Github数据</h3>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <p align="center" class="display flex">
                        <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/issues" style="text-decoration:none; margin: auto .5em;">
                            <img src="https://img.shields.io/github/issues/7Hello80/Bilibili_PrivateMessage_Bot.svg?style=flat&amp;color=red" alt="GitHub issues">
                        </a>
                        <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/stargazers" style="text-decoration:none; margin: auto .5em;">
                            <img src="https://img.shields.io/github/stars/7Hello80/Bilibili_PrivateMessage_Bot.svg?style=flat&amp;color=yellow" alt="GitHub stars">
                        </a>
                        <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/network" style="text-decoration:none; margin: auto .5em;">
                            <img src="https://img.shields.io/github/forks/7Hello80/Bilibili_PrivateMessage_Bot.svg?style=flat&amp;color=blue" alt="GitHub forks">
                        </a>
                        <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/blob/master/LICENSE" style="text-decoration:none; margin: auto .5em;">
                            <img src="https://img.shields.io/badge/License-MIT-lightgrey.svg?style=flat" alt="GitHub license">
                        </a>
                        <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/" style="margin: auto .5em; color: #238b8b;">
                            <u>如果喜欢请各位点个免费的 Star 吧！</u>
                        </a>
                    </p>
                </div>
            </div>

            <!-- 系统监控卡片 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
                <h3 class="text-lg font-medium text-gray-800 mb-4">系统资源监控</h3>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <!-- CPU使用率 -->
                    <div class="flex flex-col items-center">
                        <div class="relative w-36 h-36 mb-2">
                            <!-- 圆形进度条背景 -->
                            <svg class="w-full h-full" viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="45" fill="none" stroke="#f3f4f6" stroke-width="10"/>
                                <!-- 进度条将通过JS更新 -->
                                <circle id="cpu-progress" cx="50" cy="50" r="45" fill="none" stroke="#3b82f6" stroke-width="10" 
                                            stroke-dasharray="283" stroke-dashoffset="283" transform="rotate(-90 50 50)"/>
                            </svg>
                            <!-- 百分比文本 -->
                            <div class="absolute inset-0 flex flex-col items-center justify-center">
                                <span id="cpu-usage" class="text-2xl font-bold text-gray-800">0%</span>
                                <span class="text-xs text-gray-500">CPU</span>
                            </div>
                        </div>
                        <p class="text-xs text-gray-500">
                            核心: <span id="cpu-cores">0</span>
                        </p>
                    </div>

                    <!-- 内存使用率 -->
                    <div class="flex flex-col items-center">
                        <div class="relative w-36 h-36 mb-2">
                            <svg class="w-full h-full" viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="45" fill="none" stroke="#f3f4f6" stroke-width="10"/>
                                <circle id="mem-progress" cx="50" cy="50" r="45" fill="none" stroke="#10b981" stroke-width="10" 
                                            stroke-dasharray="283" stroke-dashoffset="283" transform="rotate(-90 50 50)"/>
                            </svg>
                            <div class="absolute inset-0 flex flex-col items-center justify-center">
                                <span id="mem-usage" class="text-2xl font-bold text-gray-800">0%</span>
                                <span class="text-xs text-gray-500">内存</span>
                            </div>
                        </div>
                        <p id="mem-details" class="text-xs text-gray-500">0/0 GB</p>
                    </div>

                    <!-- 磁盘使用率 -->
                    <div class="flex flex-col items-center">
                        <div class="relative w-36 h-36 mb-2">
                            <svg class="w-full h-full" viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="45" fill="none" stroke="#f3f4f6" stroke-width="10"/>
                                <circle id="disk-progress" cx="50" cy="50" r="45" fill="none" stroke="#8b5cf6" stroke-width="10" 
                                            stroke-dasharray="283" stroke-dashoffset="283" transform="rotate(-90 50 50)"/>
                            </svg>
                            <div class="absolute inset-0 flex flex-col items-center justify-center">
                                <span id="disk-usage" class="text-2xl font-bold text-gray-800">0%</span>
                                <span class="text-xs text-gray-500">磁盘</span>
                            </div>
                        </div>
                        <p id="disk-details" class="text-xs text-gray-500">0/0 GB</p>
                    </div>
                </div>

                <!-- 在磁盘使用率卡片后面添加网络IO监控 -->
                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6 mt-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-4">网络IO监控</h3>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <!-- 网络速度图表 -->
                        <div>
                            <h4 class="text-md font-medium text-gray-700 mb-3">实时网络速度 (KB/s)</h4>
                            <div class="relative">
                                <canvas id="network-speed-chart" class="w-full h-64"></canvas>
                            </div>
                        </div>
                        
                        <!-- 网络统计信息 -->
                        <div>
                            <h4 class="text-md font-medium text-gray-700 mb-3">网络统计</h4>
                            <div class="space-y-3">
                                <div class="flex justify-between items-center p-3 bg-blue-50 rounded-lg">
                                    <span class="text-sm text-gray-600">上传速度</span>
                                    <span id="net-sent-speed" class="text-lg font-bold text-blue-600">0 KB/s</span>
                                </div>
                                <div class="flex justify-between items-center p-3 bg-green-50 rounded-lg">
                                    <span class="text-sm text-gray-600">下载速度</span>
                                    <span id="net-recv-speed" class="text-lg font-bold text-green-600">0 KB/s</span>
                                </div>
                                <div class="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                                    <span class="text-sm text-gray-600">总上传</span>
                                    <span id="net-sent-total" class="text-sm font-medium text-gray-700">0 MB</span>
                                </div>
                                <div class="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                                    <span class="text-sm text-gray-600">总下载</span>
                                    <span id="net-recv-total" class="text-sm font-medium text-gray-700">0 MB</span>
                                </div>
                                <div class="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                                    <span class="text-sm text-gray-600">数据包错误</span>
                                    <span id="net-errors" class="text-sm font-medium text-red-600">0</span>
                                </div>
                                <div class="flex justify-between items-center p-3 bg-gray-50 rounded-lg">
                                    <span class="text-sm text-gray-600">数据包丢弃</span>
                                    <span id="net-drops" class="text-sm font-medium text-orange-600">0</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                    
                <!-- 系统负载 (仅Unix系统) -->
                <div id="load-average-container" class="mt-6 pt-4 border-t border-gray-100" style="display: none;">
                    <h4 class="text-sm font-medium text-gray-700 mb-3">系统负载平均值</h4>
                    <div class="grid grid-cols-3 gap-3">
                        <div class="p-3 bg-gray-50 rounded-lg text-center">
                            <p class="text-xs text-gray-500">1分钟</p>
                            <p id="load-1" class="text-lg font-bold text-gray-800">0.00</p>
                        </div>
                        <div class="p-3 bg-gray-50 rounded-lg text-center">
                            <p class="text-xs text-gray-500">5分钟</p>
                            <p id="load-5" class="text-lg font-bold text-gray-800">0.00</p>
                        </div>
                        <div class="p-3 bg-gray-50 rounded-lg text-center">
                            <p class="text-xs text-gray-500">15分钟</p>
                            <p id="load-15" class="text-lg font-bold text-gray-800">0.00</p>
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
                    <button id="restart-btn" onclick="restartBot()" 
                            class="flex items-center justify-center px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition transform hover:-translate-y-0.5">
                        <i class="fa fa-redo mr-2"></i>重启机器人
                    </button>
                    <button onclick="manualCheckUpdate()" 
                            class="flex items-center justify-center px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-500 transition transform hover:-translate-y-0.5">
                        <i class="fa fa-sync-alt mr-2"></i>检查更新
                    </button>
                </div>
            </div>

            <!-- 公告展示栏 -->
            <div class="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6">
                <h3 class="text-lg font-medium text-blue-800 mb-4">系统公告</h3>
                <p id="announcement-text" class="text-sm text-blue-700">
                </p>
            </div>

            <!-- 快速操作 -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-4">快速操作</h3>
                    <div class="space-y-3">
                        <button onclick="showSection('accounts')" class="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition">
                            <div class="flex items-center space-x-3">
                                <i class="fa fa-users text-gray-400"></i>
                                <span>管理账号</span>
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
                        <button onclick="showSection('about')" class="w-full flex items-center justify-between p-3 text-left bg-gray-50 hover:bg-gray-100 rounded-lg transition">
                            <div class="flex items-center space-x-3">
                                <i class="fa fa-user text-gray-400"></i>
                                <span>关于我们</span>
                            </div>
                            <i class="fa fa-chevron-right text-gray-400"></i>
                        </button>
                    </div>
                </div>

                <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-4">系统信息</h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">系统类型</span>
                            <span class="font-medium">''' + system_name + '''</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">系统版本</span>
                            <span class="font-medium">''' + system_version + '''</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">系统发行版</span>
                            <span class="font-medium">''' + system_distribution + '''</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">面板版本</span>
                            <span class="font-medium">v''' + Version + '''</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">运行时间</span>
                            <span id="uptime" class="font-medium">--</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">最后更新</span>
                            <span id="last-update" class="font-medium">--</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 多账号管理 -->
        <div id="accounts" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center justify-between">
                    <div class="flex items-center">
                        <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                            <i class="fa fa-bars"></i>
                        </button>
                        <div>
                            <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">多账号管理</h2>
                            <p class="text-gray-600 mt-2">管理多个B站账号的自动回复</p>
                        </div>
                    </div>
                    <button onclick="showAddAccountModal()" 
                            class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 transition flex items-center">
                        <i class="fa fa-plus mr-2"></i>添加账号
                    </button>
                </div>
            </div>

            <!-- 账号列表 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100 mb-6">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-medium text-gray-800">账号列表</h3>
                </div>
                <div id="accounts-list" class="p-6">
                    <div class="text-center text-gray-500 py-8">
                        <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                        <p>加载中...</p>
                    </div>
                </div>
            </div>

            <!-- 全局关键词管理 -->
            <div class="bg-white rounded-xl shadow-sm border border-gray-100">
                <div class="px-6 py-4 border-b border-gray-200">
                    <h3 class="text-lg font-medium text-gray-800">全局关键词</h3>
                    <p class="text-sm text-gray-600 mt-1">这些关键词对所有账号生效</p>
                </div>
                <div class="p-6">
                    <div id="global-keywords-list">
                        <div class="text-center text-gray-500 py-4">
                            <i class="fa fa-spinner fa-spin text-xl mb-2"></i>
                            <p>加载中...</p>
                        </div>
                    </div>
                    <div class="mt-4">
                        <button onclick="showGlobalKeywordModal()" 
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition flex items-center">
                            <i class="fa fa-plus mr-2"></i>添加全局关键词
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- 运行日志 -->
        <div id="logs" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
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
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition flex items-center">
                            <i class="fa fa-sync-alt mr-2"></i>刷新
                        </button>
                        <button onclick="clearAllLogs()" 
                                class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 transition flex items-center">
                            <i class="fa fa-trash mr-2"></i>清空日志
                        </button>
                    </div>
                </div>
                <div class="p-4 lg:p-6">
                    <!-- 日志统计信息 -->
                    <div class="mb-4 grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div class="bg-blue-50 border border-blue-200 rounded-lg p-3 text-center">
                            <div class="text-blue-600 font-semibold text-sm">总日志数</div>
                            <div id="total-logs-count" class="text-2xl font-bold text-blue-700">--</div>
                        </div>
                        <div class="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                            <div class="text-green-600 font-semibold text-sm">信息日志</div>
                            <div id="info-logs-count" class="text-2xl font-bold text-green-700">--</div>
                        </div>
                        <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-center">
                            <div class="text-yellow-600 font-semibold text-sm">警告日志</div>
                            <div id="warning-logs-count" class="text-2xl font-bold text-yellow-700">--</div>
                        </div>
                        <div class="bg-red-50 border border-red-200 rounded-lg p-3 text-center">
                            <div class="text-red-600 font-semibold text-sm">错误日志</div>
                            <div id="error-logs-count" class="text-2xl font-bold text-red-700">--</div>
                        </div>
                    </div>

                    <!-- 日志过滤器 -->
                    <div class="mb-4 flex flex-wrap gap-2">
                        <button onclick="setLogFilter('all')" id="filter-all" class="log-filter-btn active px-3 py-1 bg-blue-600 text-white rounded-full text-sm">全部</button>
                        <button onclick="setLogFilter('info')" id="filter-info" class="log-filter-btn px-3 py-1 bg-gray-200 text-gray-700 rounded-full text-sm">信息</button>
                        <button onclick="setLogFilter('warning')" id="filter-warning" class="log-filter-btn px-3 py-1 bg-gray-200 text-gray-700 rounded-full text-sm">警告</button>
                        <button onclick="setLogFilter('error')" id="filter-error" class="log-filter-btn px-3 py-1 bg-gray-200 text-gray-700 rounded-full text-sm">错误</button>
                        <button onclick="setLogFilter('bot')" id="filter-bot" class="log-filter-btn px-3 py-1 bg-gray-200 text-gray-700 rounded-full text-sm">机器人</button>
                    </div>

                    <!-- 日志搜索 -->
                    <div class="mb-4 relative">
                        <input type="text" id="log-search" placeholder="搜索日志内容..." 
                               class="w-full px-4 py-2 pl-10 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                               onkeyup="filterLogs()">
                        <i class="fa fa-search absolute left-3 top-3 text-gray-400"></i>
                    </div>

                    <!-- 日志容器 -->
                    <div id="log-container" class="bg-gray-900 text-gray-300 font-mono text-sm rounded-lg p-4 h-96 overflow-y-auto">
                        <div class="text-center text-gray-500 py-8">
                            <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
                            <p>正在加载日志...</p>
                        </div>
                    </div>

                    <!-- 日志控制 -->
                    <div class="mt-4 flex justify-between items-center">
                        <div class="text-sm text-gray-600">
                            显示 <span id="displayed-logs-count">0</span> 条日志，共 <span id="total-displayed-logs">0</span> 条
                        </div>
                        <div class="flex space-x-2">
                            <button onclick="scrollLogsToTop()" class="px-3 py-1 bg-gray-600 text-white rounded text-sm hover:bg-gray-700 transition">
                                <i class="fa fa-arrow-up mr-1"></i>顶部
                            </button>
                            <button onclick="scrollLogsToBottom()" class="px-3 py-1 bg-gray-600 text-white rounded text-sm hover:bg-gray-700 transition">
                                <i class="fa fa-arrow-down mr-1"></i>底部
                            </button>
                            <button onclick="toggleAutoScroll()" id="auto-scroll-btn" class="px-3 py-1 bg-green-600 text-white rounded text-sm hover:bg-green-700 transition">
                                <i class="fa fa-magic mr-1"></i>自动滚动
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 账号设置 -->
        <div id="admin" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
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

        <!-- 图床管理 -->
        <div id="image_bed" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">图床管理</h2>
                        <p class="text-gray-600 mt-2">管理上传的图片，可用于自动回复</p>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- 图片上传区域 -->
                <div class="lg:col-span-1">
                    <div class="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                        <h3 class="text-lg font-semibold text-gray-800 mb-4 flex items-center">
                            <i class="fa fa-cloud-upload-alt text-blue-500 mr-2"></i>上传图片
                        </h3>
                        
                        <!-- 上传表单 -->
                        <form id="upload-image-form" enctype="multipart/form-data" class="space-y-4">
                            <!-- Layui 选择器 -->
                            <div class="space-y-2">
                                <label class="block text-sm font-medium text-gray-700 mb-2">选择上传账号</label>
                                
                                <div class="layui-form">
                                    <select id="upload-account" lay-search lay-verify="required">
                                        <option value="">选择上传账号...</option>
                                        <!-- 选项将通过JS动态加载 -->
                                    </select>
                                </div>
                                
                                <p class="text-xs text-gray-500 mt-1">需要有效的 SESSDATA 和 bili_jct</p>
                            </div>

                            <!-- 上传区域 -->
                            <div class="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center transition-all duration-300 hover:border-blue-400 hover:bg-blue-50 cursor-pointer group" id="upload-area">
                                <input type="file" id="image-file" name="file_up" accept="image/jpeg,image/jpg,image/png,image/gif,image/webp" class="hidden">
                                <div class="cursor-pointer">
                                    <i class="fa fa-cloud-upload-alt text-3xl text-gray-400 mb-3 transition-colors group-hover:text-blue-400"></i>
                                    <p class="text-gray-700 font-medium text-sm">点击或拖拽上传</p>
                                    <p class="text-xs text-gray-500 mt-1">支持 JPG, PNG, GIF, WebP</p>
                                    <p class="text-xs text-gray-500">最大 10MB</p>
                                </div>
                            </div>
                            
                            <!-- 文件信息 -->
                            <div id="file-info" class="hidden">
                                <div class="bg-blue-50 border border-blue-200 rounded-xl p-4">
                                    <div class="flex items-center justify-between">
                                        <div class="flex items-center space-x-3">
                                            <i class="fa fa-file-image text-blue-500"></i>
                                            <div>
                                                <p class="text-sm font-medium text-blue-800" id="file-name"></p>
                                                <p class="text-xs text-blue-600 mt-1" id="file-size"></p>
                                            </div>
                                        </div>
                                        <button type="button" onclick="resetFileSelection()" class="text-blue-600 hover:text-blue-800 transition-colors">
                                            <i class="fa fa-times"></i>
                                        </button>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- 上传进度 -->
                            <div id="upload-progress" class="hidden">
                                <div class="flex items-center justify-between mb-2">
                                    <span class="text-sm font-medium text-gray-700">上传进度</span>
                                    <span id="progress-text" class="text-sm font-semibold text-blue-600">0%</span>
                                </div>
                                <div class="w-full bg-gray-200 rounded-full h-2 mb-4 overflow-hidden">
                                    <div id="progress-bar" class="bg-gradient-to-r from-blue-500 to-purple-600 h-2 rounded-full transition-all duration-300" style="width: 0%"></div>
                                </div>
                            </div>
                            
                            <!-- 操作按钮 -->
                            <div class="flex space-x-3">
                                <button type="submit" id="upload-button" 
                                        class="flex-1 px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center shadow-sm hover:shadow-md">
                                    <i class="fa fa-upload mr-2"></i>
                                    <span>上传图片</span>
                                </button>
                                <button type="button" id="cancel-upload-btn" 
                                        class="px-4 py-3 bg-gray-500 text-white rounded-lg hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-gray-400 transition-all duration-200 hidden shadow-sm hover:shadow-md">
                                    <i class="fa fa-times"></i>
                                </button>
                            </div>
                        </form>
                        
                        <!-- 使用说明 -->
                        <div class="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
                            <h4 class="text-sm font-semibold text-gray-700 mb-3 flex items-center">
                                <i class="fa fa-info-circle text-blue-500 mr-2"></i>
                                使用说明
                            </h4>
                            <ul class="text-xs text-gray-600 space-y-2">
                                <li class="flex items-start">
                                    <i class="fa fa-check-circle text-green-500 mr-2 mt-0.5 flex-shrink-0"></i>
                                    <span>图片将存储在 B 站图床，稳定可靠</span>
                                </li>
                                <li class="flex items-start">
                                    <i class="fa fa-check-circle text-green-500 mr-2 mt-0.5 flex-shrink-0"></i>
                                    <span>在关键词回复中使用: <code class="bg-blue-100 text-blue-700 px-1 rounded text-xs">[bili_image:图片URL]</code>可发送图片，只能使用b站图床的图片URL，回复中只能单独出现，不能与其他文字混合使用</span>
                                </li>
                                <li class="flex items-start">
                                    <i class="fa fa-check-circle text-green-500 mr-2 mt-0.5 flex-shrink-0"></i>
                                    <span>点击图片可预览，右键可复制 URL 或删除</span>
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>

                <!-- 图片列表 -->
                <div class="lg:col-span-2">
                    <div class="bg-white rounded-xl shadow-sm border border-gray-200">
                        <div class="px-6 py-4 border-b border-gray-200">
                            <div class="flex items-center justify-between">
                                <div>
                                    <h3 class="text-lg font-semibold text-gray-800">图片库</h3>
                                    <p class="text-sm text-gray-600 mt-1">共 <span id="images-count" class="font-semibold text-blue-600">0</span> 张图片</p>
                                </div>
                                <div class="flex items-center space-x-2">
                                    <button onclick="loadImages()" class="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-all duration-200" title="刷新">
                                        <i class="fa fa-refresh"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                        
                        <div class="p-4">
                            <!-- 空状态 -->
                            <div id="empty-images" class="text-center py-12 hidden">
                                <div class="max-w-xs mx-auto">
                                    <i class="fa fa-images text-5xl text-gray-300 mb-4"></i>
                                    <p class="text-gray-500 font-medium text-lg">暂无图片</p>
                                    <p class="text-sm text-gray-400 mt-2">上传第一张图片开始使用图床功能</p>
                                </div>
                            </div>

                            <!-- 图片网格 -->
                            <div id="images-list" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                                <div class="text-center text-gray-500 py-8 col-span-full">
                                    <i class="fa fa-spinner fa-spin text-xl mb-2 text-blue-500"></i>
                                    <p class="text-sm">加载图片中...</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 图片预览模态框 -->
        <div id="image-preview-modal" class="hidden fixed inset-0 bg-black bg-opacity-75 z-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-xl max-w-4xl max-h-full overflow-hidden w-full">
                <div class="p-4 border-b border-gray-200 flex justify-between items-center">
                    <h3 class="text-lg font-semibold text-gray-800" id="preview-title">图片预览</h3>
                    <button onclick="closePreviewModal()" class="p-2 hover:bg-gray-100 rounded-lg transition">
                        <i class="fa fa-times text-gray-600"></i>
                    </button>
                </div>
                <div class="p-6 max-h-96 overflow-auto">
                    <img id="preview-image" src="" alt="预览" class="max-w-full max-h-80 object-contain mx-auto rounded-lg" referrerpolicy="no-referrer">
                </div>
                <div class="p-4 border-t border-gray-200 bg-gray-50 flex justify-between items-center">
                    <div class="flex space-x-2">
                        <button onclick="copyImageUrl(currentPreviewUrl)" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center">
                            <i class="fa fa-copy mr-2"></i>复制URL
                        </button>
                    </div>
                    <button onclick="deleteImage(currentPreviewUrl)" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition flex items-center">
                        <i class="fa fa-trash mr-2"></i>删除
                    </button>
                </div>
            </div>
        </div>

        <!-- 关于我们页面 -->
        <div id="about" class="section p-4 lg:p-6" style="display: none;">
            <div class="mb-6">
                <div class="flex items-center">
                    <!-- 移动端菜单按钮 -->
                    <button class="mobile-menu-button lg:hidden mr-3 p-2 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition">
                        <i class="fa fa-bars"></i>
                    </button>
                    <div>
                        <h2 class="text-2xl lg:text-3xl font-bold text-gray-800">关于我们</h2>
                        <p class="text-gray-600 mt-2">项目开发团队介绍</p>
                    </div>
                </div>
            </div>

            <div class="max-w-4xl mx-auto">
                <!-- 开发者信息卡片 -->
                <div class="bg-white rounded-xl shadow-lg overflow-hidden mb-8">
                    <div class="p-6 md:p-8">
                        <div class="flex flex-col md:flex-row items-center gap-6">
                            <div class="w-32 h-32 rounded-full bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center text-white text-4xl font-bold shadow-lg">
                                <img src="https://avatars.githubusercontent.com/u/221005642?v=4" alt="开发者头像" class="w-full h-full rounded-full">
                            </div>
                            <div class="flex-1 text-center md:text-left">
                                <h1 class="text-3xl font-bold text-gray-800 mb-2">淡意往事</h1>
                                <p class="text-lg text-gray-600 mb-4">开发人员</p>
                                <p class="text-gray-500 leading-relaxed">一名热爱技术的开发者。本人目前还是在校生，没啥资金，希望可以打赏一下我们</p>
                                <div class="flex justify-center md:justify-start space-x-4 mt-4">
                                    <a href="https://github.com/7hello80" class="text-gray-500 hover:text-blue-500 transition-colors duration-200" target="_blank">
                                        <i class="fab fa-github text-xl"></i>
                                    </a>
                                    <a href="mailto:3399711161@qq.com" class="text-gray-500 hover:text-blue-500 transition-colors duration-200" target="_blank">
                                        <i class="fa fa-envelope text-xl"></i>
                                    </a>
                                    <a href="https://qm.qq.com/q/swTIhx4tF" class="text-gray-500 hover:text-blue-500 transition-colors duration-200" target="_blank">
                                        <i class="fab fa-qq text-xl"></i>
                                    </a>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    <div class="lg:col-span-2 space-y-8">
                        <!-- 前端技术栈 -->
                        <div class="bg-white rounded-xl shadow-lg p-6">
                            <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                                <i class="fa fa-code mr-2 text-blue-500"></i> 前端技术栈
                            </h2>
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-code text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">HTML/CSS/JavaScript</h3>
                                        <p class="text-sm text-gray-500">前端基础技术</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fab fa-css3 text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Tailwind CSS</h3>
                                        <p class="text-sm text-gray-500">实用优先的CSS框架</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-bolt text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">HTMX</h3>
                                        <p class="text-sm text-gray-500">增强HTML的JavaScript库</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-font text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Font Awesome</h3>
                                        <p class="text-sm text-gray-500">图标字体库</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fab fa-css3 text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">LayUI</h3>
                                        <p class="text-sm text-gray-500">极简模块化 Web UI 组件库</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-blue-100 to-blue-200 flex items-center justify-center mr-3">
                                        <i class="fas fa-code text-blue-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Chart.js</h3>
                                        <p class="text-sm text-gray-500">应用程序开发者的图表库</p>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- 后端技术栈 -->
                        <div class="bg-white rounded-xl shadow-lg p-6">
                            <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                                <i class="fa fa-server mr-2 text-green-500"></i> 后端技术栈
                            </h2>
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-green-200 hover:bg-green-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-green-100 to-green-200 flex items-center justify-center mr-3">
                                        <i class="fab fa-python text-green-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Python</h3>
                                        <p class="text-sm text-gray-500">编程语言</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-green-200 hover:bg-green-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-green-100 to-green-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-flask text-green-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Flask</h3>
                                        <p class="text-sm text-gray-500">Python Web框架</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-green-200 hover:bg-green-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-green-100 to-green-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-database text-green-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">JSON</h3>
                                        <p class="text-sm text-gray-500">数据存储格式</p>
                                    </div>
                                </div>
                                <div class="flex items-center p-3 rounded-lg border border-gray-100 hover:border-green-200 hover:bg-green-50 transition-all duration-200">
                                    <div class="w-10 h-10 rounded-lg bg-gradient-to-r from-green-100 to-green-200 flex items-center justify-center mr-3">
                                        <i class="fa fa-shield-alt text-green-600"></i>
                                    </div>
                                    <div>
                                        <h3 class="font-semibold text-gray-800">Werkzeug</h3>
                                        <p class="text-sm text-gray-500">密码安全加密</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 支持与打赏 -->
                    <div class="lg:col-span-1">
                        <div class="bg-white rounded-xl shadow-lg p-6 sticky top-24">
                            <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                                <i class="fa fa-heart mr-2 text-red-500"></i> 支持与打赏
                            </h2>
                            <p class="text-gray-600 mb-6">如果我的项目对您有帮助，欢迎打赏支持，这将激励我持续创作和更新！</p>
                            <div class="space-y-6">
                                <div class="text-center p-4 rounded-lg border-2 border-dashed border-gray-200 hover:border-blue-300 transition-colors duration-200">
                                    <h3 class="font-semibold text-gray-800 mb-2">微信赞赏</h3>
                                    <div class="w-40 h-40 mx-auto bg-gray-100 rounded-lg flex items-center justify-center mb-2">
                                        <img src="https://store.bzks.qzz.io/src/png/vx-D_zisWkG.png" alt="微信赞赏二维码" class="w-full h-full rounded-lg">
                                    </div>
                                    <p class="text-sm text-gray-500">扫描二维码赞赏</p>
                                </div>
                                <div class="text-center p-4 rounded-lg border-2 border-dashed border-gray-200 hover:border-blue-300 transition-colors duration-200">
                                    <h3 class="font-semibold text-gray-800 mb-2">支付宝</h3>
                                    <div class="w-40 h-40 mx-auto bg-gray-100 rounded-lg flex items-center justify-center mb-2">
                                        <img src="https://store.bzks.qzz.io/src/png/alipay-BJaNLw5H.png" alt="支付宝二维码" class="w-full h-full rounded-lg">
                                    </div>
                                    <p class="text-sm text-gray-500">扫描二维码打赏</p>
                                </div>
                            </div>
                            <div class="mt-6 p-4 bg-blue-50 rounded-lg">
                                <p class="text-sm text-blue-700 text-center">感谢您的每一份支持！❤️</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!--如果进行二次开发，此段版权信息不得移除且应明显地标注于页面上-->
        <footer class="bg-white border-t border-gray-200 py-4 px-6 shadow-inner" style="margin-top: 20px;">
            <div class="flex flex-col md:flex-row justify-between items-center">
                <div class="text-center md:text-left mb-2 md:mb-0">
                    <p class="text-sm text-gray-600">
                        Copyright &copy; 2025 淡意往事.
                    </p>
                    <p class="text-xs text-gray-500 mt-1">
                        使用 <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/blob/main/LICENSE" target="_blank" class="text-gray-700 hover:text-gray-600 transition" title="MIT许可协议">MIT许可协议</a> 开放源代码
                    </p>
                </div>
                <div class="flex items-center space-x-4">
                    <a href="https://github.com/7Hello80/Bilibili_PrivateMessage_Bot" target="_blank" class="text-gray-700 hover:text-gray-600 transition" title="GitHub">
                        <i class="fab fa-github text-lg"></i>
                    </a>
                    <a href="https://space.bilibili.com/2142524663?spm_id_from=333.1007.0.0" target="_blank" class="text-gray-700 hover:text-bilibili transition" title="Bilibili">
                        <i class="fab fa-bilibili text-lg"></i>
                    </a>
                </div>
            </div>
            <div class="mt-2 pt-2 border-t border-gray-100 text-center">
                <p class="text-xs text-gray-500">
                    系统版本: v''' + ConfigManage.base64_decode(CURRENT_VERSION) + '''
                </p>
            </div>
        </footer>
    </div>
</div>

<!-- 添加账号模态框 -->
<div id="add-account-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">添加新账号</h3>
            </div>
            <div class="p-6">
                <form id="add-account-form">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">账号名称</label>
                            <input type="text" name="name" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="例如: 主账号">
                        </div>
                        
                        <!-- 扫码登录区域 -->
                        <div class="border border-gray-200 rounded-lg p-4 bg-gray-50">
                            <div class="flex items-center justify-between mb-3">
                                <h4 class="text-lg font-medium text-gray-800">扫码登录</h4>
                                <button type="button" id="start-qrcode-login" 
                                        class="px-4 py-2 bg-bilibili text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition flex items-center">
                                    <i class="fa fa-qrcode mr-2"></i>扫码登录
                                </button>
                            </div>
                            <div id="qrcode-container" class="hidden">
                                <div class="text-center mb-4">
                                    <img id="qrcode-img" src="" alt="二维码" class="mx-auto mb-2 border border-gray-300 rounded">
                                    <p id="qrcode-status" class="text-sm text-gray-600">请使用哔哩哔哩APP扫码登录</p>
                                </div>
                                <div class="flex justify-center">
                                    <button type="button" id="cancel-qrcode-login" 
                                            class="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-gray-500 transition">
                                        取消扫码
                                    </button>
                                </div>
                            </div>
                        </div>
                        
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">SESSDATA</label>
                                <input type="password" name="sessdata" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">BILI_JCT</label>
                                <input type="password" name="bili_jct" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">SELF_UID</label>
                                <input type="number" name="self_uid" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">DEVICE_ID</label>
                                <input type="text" name="device_id" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                       value="">
                            </div>
                            
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">DedeUserID</label>
                                <input type="text" name="DedeUserID" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                       value="">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">DedeUserID__ckMd5</label>
                                <input type="text" name="DedeUserID__ckMd5" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                       value="">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">SID</label>
                                <input type="text" name="sid" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                       value="">
                            </div>
                        </div>
                        <div class="flex items-center justify-between space-x-4">
                            <div class="flex items-center">
                                <input type="checkbox" name="enabled" id="account-enabled" checked
                                       class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                <label for="account-enabled" class="ml-2 text-sm text-gray-700">启用此账号</label>
                            </div>
                            <div class="flex items-center space-x-4">
                                <div class="flex items-center">
                                    <input type="checkbox" name="at_user" id="account-at-user"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="account-at-user" class="ml-2 text-sm text-gray-700">艾特用户</label>
                                </div>
                                <div class="flex items-center">
                                    <input type="checkbox" name="auto_focus" id="account-auto-focus"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="account-auto-focus" class="ml-2 text-sm text-gray-700">自动关注</label>
                                </div>
                                <div class="flex items-center">
                                    <input type="checkbox" name="no_focus_hf" id="account-no-focus"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="account-no-focus" class="ml-2 text-sm text-gray-700">开启未关注也回复功能</label>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- 在添加账号模态框中添加关注自动回复配置 -->
                    <div class="flex items-center justify-between space-x-4 mt-4">
                        <div class="flex items-center">
                            <input type="checkbox" id="add-account-auto-reply-follow" name="auto_reply_follow"
                                class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                            <label for="add-account-auto-reply-follow" class="ml-2 text-sm text-gray-700">启用关注自动回复</label>
                        </div>
                    </div>

                    <!-- 添加关注回复消息输入框 -->
                    <div id="add-follow-reply-container" class="mt-4 hidden">
                        <label class="block text-sm font-medium text-gray-700 mb-2">关注回复消息</label>
                        <textarea id="add-account-follow-reply-message" name="follow_reply_message"
                                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                rows="3"
                                placeholder="请输入关注自动回复的消息内容（只能设置一条）">感谢关注！</textarea>
                        <p class="text-xs text-gray-500 mt-1">此消息将发送给新关注您的用户</p>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideAddAccountModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            添加账号
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- 编辑账号模态框 -->
<div id="edit-account-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">编辑账号</h3>
            </div>
            <div class="p-6">
                <form id="edit-account-form">
                    <input type="hidden" id="edit-account-index" name="account_index">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">账号名称</label>
                            <input type="text" id="edit-account-name" name="name" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="例如: 主账号">
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">SESSDATA</label>
                                <input type="password" id="edit-account-sessdata" name="sessdata" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">BILI_JCT</label>
                                <input type="password" id="edit-account-bili_jct" name="bili_jct" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">SELF_UID</label>
                                <input type="number" id="edit-account-self_uid" name="self_uid" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">DEVICE_ID</label>
                                <input type="text" id="edit-account-device_id" name="device_id" required
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                        </div>
                        <div class="flex items-center justify-between space-x-4">
                            <div class="flex items-center">
                                <input type="checkbox" id="edit-account-enabled" name="enabled"
                                       class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                <label for="edit-account-enabled" class="ml-2 text-sm text-gray-700">启用此账号</label>
                            </div>
                            <div class="flex items-center space-x-4">
                                <div class="flex items-center">
                                    <input type="checkbox" id="edit-account-at-user" name="at_user"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="edit-account-at-user" class="ml-2 text-sm text-gray-700">艾特用户</label>
                                </div>
                                <div class="flex items-center">
                                    <input type="checkbox" id="edit-account-auto-focus" name="auto_focus"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="edit-account-auto-focus" class="ml-2 text-sm text-gray-700">自动关注</label>
                                </div>
                                <div class="flex items-center">
                                    <input type="checkbox" name="no_focus_hf" id="edit-account-no-focus"
                                           class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                                    <label for="edit-account-no-focus" class="ml-2 text-sm text-gray-700">开启未关注也回复功能</label>
                                </div>
                            </div>
                        </div>

                        <!-- 账号关键词管理 -->
                        <div class="mt-6 pt-6 border-t border-gray-200">
                            <h4 class="text-lg font-medium text-gray-800 mb-4">账号关键词管理</h4>
                            <!-- 添加关键词表单 -->
                            <div class="bg-gray-50 rounded-lg p-4 mb-4">
                                <h5 class="text-md font-medium text-gray-700 mb-3">添加新关键词</h5>
                                <div class="space-y-4">
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-2">关键词</label>
                                        <input type="text" id="edit-account-keyword-input" 
                                            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                            placeholder="请输入关键词">
                                    </div>
                                    <div>
                                        <label class="block text-sm font-medium text-gray-700 mb-2">回复内容</label>
                                        <textarea id="edit-account-reply-input" rows="4"
                                            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition resize-vertical"
                                            placeholder="请输入回复内容（支持换行）"></textarea>
                                    </div>
                                    <div class="flex justify-between items-center">
                                        <!-- 艾特用户提示 -->
                                        <div class="text-sm text-gray-600">
                                            提示：在回复内容中使用 <code class="bg-gray-200 px-1 rounded">[at_user]</code> 来@用户，关键词处可使用<code class="bg-gray-200 px-1 rounded">;</code>分割关键词，用以达到使用多个关键词回复同一内容的功能
                                        </div>
                                        <button type="button" onclick="addAccountKeyword()"
                                                class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 transition flex items-center">
                                            <i class="fa fa-plus mr-2"></i>添加关键词
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- 关键词列表 -->
                            <div id="edit-account-keywords-list" class="space-y-2 max-h-60 overflow-y-auto">
                                <!-- 关键词列表将在这里动态生成 -->
                            </div>
                        </div>
                    </div>
                    <!-- 在编辑账号模态框中添加关注自动回复配置 -->
                    <div class="flex items-center justify-between space-x-4 mt-4">
                        <div class="flex items-center">
                            <input type="checkbox" id="edit-account-auto-reply-follow" name="auto_reply_follow"
                                class="w-4 h-4 text-primary-600 border-gray-300 rounded focus:ring-primary-500">
                            <label for="edit-account-auto-reply-follow" class="ml-2 text-sm text-gray-700">启用关注自动回复</label>
                        </div>
                    </div>

                    <!-- 添加关注回复消息输入框 -->
                    <div id="follow-reply-container" class="mt-4 hidden">
                        <label class="block text-sm font-medium text-gray-700 mb-2">关注回复消息</label>
                        <textarea id="edit-account-follow-reply-message" name="follow_reply_message"
                                class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                rows="3"
                                placeholder="请输入关注自动回复的消息内容（只能设置一条）">感谢关注！</textarea>
                        <p class="text-xs text-gray-500 mt-1">此消息将发送给新关注您的用户</p>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideEditAccountModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            保存修改
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- 创建插件模态框 -->
<div id="create-plugin-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-md">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">创建新插件</h3>
            </div>
            <div class="p-6">
                <form id="create-plugin-form">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">插件名称</label>
                            <input type="text" name="name" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="例如: my_awesome_plugin">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">插件类型</label>
                            <select name="type" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                                <option value="base">基础插件</option>
                                <option value="message">消息处理</option>
                                <option value="event">事件处理</option>
                                <option value="api">API扩展</option>
                                <option value="analysis">数据分析</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">作者</label>
                            <input type="text" name="author" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="您的名字">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">版本</label>
                            <input type="text" name="version" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   value="1.0.0">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">描述</label>
                            <textarea name="description" 
                                      class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                      rows="3"
                                      placeholder="插件功能描述"></textarea>
                        </div>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideCreatePluginModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            创建插件
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- 插件详情模态框 -->
<div id="plugin-detail-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden overflow-y-auto">
    <div class="flex items-center justify-center min-h-full p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-5xl max-h-[92vh] flex flex-col my-4">
            <div class="p-6 pb-4 border-b border-gray-200">
                <div class="flex items-start justify-between gap-3 flex-wrap">
                    <div class="flex items-center space-x-3 flex-wrap gap-2">
                        <h3 class="text-xl font-bold text-gray-800 break-all" id="plugin-detail-title">插件详情</h3>
                        <span id="plugin-detail-version" class="text-sm px-2 py-1 bg-blue-100 text-blue-800 rounded"></span>
                        <span id="plugin-detail-status-badge" class="text-sm px-2 py-1 rounded"></span>
                        <span id="plugin-detail-update-badge" class="text-sm px-2 py-1 bg-red-100 text-red-700 rounded hidden">有新版本</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <!-- 快捷操作 -->
                        <button id="plugin-detail-toggle-btn" onclick="togglePluginFromDetail()"
                                class="px-3 py-1 text-sm bg-yellow-600 hover:bg-yellow-700 text-white rounded transition">禁用</button>
                        <button onclick="reloadPlugin(pluginDetailName)"
                                class="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded transition">重载</button>
                        <button onclick="backupPlugin(pluginDetailName)"
                                class="px-3 py-1 text-sm bg-teal-600 hover:bg-teal-700 text-white rounded transition">备份</button>
                        <button onclick="checkPluginUpdate(pluginDetailName)"
                                class="px-3 py-1 text-sm bg-orange-600 hover:bg-orange-700 text-white rounded transition">检查更新</button>
                        <button onclick="hidePluginDetailModal()" class="p-2 hover:bg-gray-100 rounded-lg transition">
                            <i class="fa fa-times text-gray-500"></i>
                        </button>
                    </div>
                </div>
                <!-- Tab 导航 -->
                <div class="flex flex-wrap gap-1 mt-4 border-b border-gray-200">
                    <button onclick="switchPluginTab('info')" data-plugin-tab="info"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-blue-600 border-b-2 border-blue-600">信息</button>
                    <button onclick="switchPluginTab('readme')" data-plugin-tab="readme"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">README</button>
                    <button onclick="switchPluginTab('config')" data-plugin-tab="config"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">配置</button>
                    <button onclick="switchPluginTab('logs')" data-plugin-tab="logs"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">日志</button>
                    <button onclick="switchPluginTab('metrics')" data-plugin-tab="metrics"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">指标</button>
                    <button onclick="switchPluginTab('apitest')" data-plugin-tab="apitest"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">API测试</button>
                    <button onclick="switchPluginTab('source')" data-plugin-tab="source"
                            class="plugin-detail-tab px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800">源码</button>
                </div>
            </div>
            <div class="p-6 overflow-y-auto flex-1 min-h-0">
                <!-- 信息 tab -->
                <div id="plugin-tab-info" class="plugin-detail-content">
                    <div id="plugin-detail-info" class="space-y-3"></div>
                </div>
                <!-- README tab -->
                <div id="plugin-tab-readme" class="plugin-detail-content hidden">
                    <div id="plugin-detail-readme" class="markdown-body p-4 bg-gray-50 rounded-lg whitespace-pre-wrap text-sm text-gray-700"></div>
                </div>
                <!-- 配置 tab -->
                <div id="plugin-tab-config" class="plugin-detail-content hidden">
                    <p class="text-sm text-gray-500 mb-3">编辑插件配置(JSON)，保存后自动重载插件生效</p>
                    <textarea id="plugin-config-editor" rows="16"
                              class="w-full px-4 py-3 border border-gray-300 rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"></textarea>
                    <div id="plugin-config-error" class="mt-2 text-sm text-red-600 hidden"></div>
                    <div class="mt-3 flex justify-end space-x-3">
                        <button onclick="savePluginConfig()"
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center">
                            <i class="fa fa-save mr-2"></i>保存配置
                        </button>
                    </div>
                </div>
                <!-- 日志 tab -->
                <div id="plugin-tab-logs" class="plugin-detail-content hidden">
                    <div class="flex justify-end mb-3">
                        <button onclick="loadPluginLogs(pluginDetailName)"
                                class="px-3 py-1 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition">
                            <i class="fa fa-refresh mr-1"></i>刷新日志
                        </button>
                    </div>
                    <div class="text-sm text-gray-600 mb-2">插件自身日志(plugins/&lt;名称&gt;/plugin.log)：</div>
                    <pre id="plugin-detail-file-logs" class="bg-gray-900 text-gray-200 p-4 rounded-lg overflow-auto max-h-64 text-xs whitespace-pre-wrap"></pre>
                    <div class="text-sm text-gray-600 mt-4 mb-2">机器人运行日志中的相关行：</div>
                    <pre id="plugin-detail-bot-logs" class="bg-gray-900 text-gray-200 p-4 rounded-lg overflow-auto max-h-64 text-xs whitespace-pre-wrap"></pre>
                </div>
                <!-- 指标 tab -->
                <div id="plugin-tab-metrics" class="plugin-detail-content hidden">
                    <div class="flex justify-end mb-3">
                        <button onclick="loadPluginMetrics(pluginDetailName)"
                                class="px-3 py-1 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition">
                            <i class="fa fa-refresh mr-1"></i>刷新指标
                        </button>
                    </div>
                    <div id="plugin-detail-metric-cards" class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4"></div>
                    <h4 class="text-sm font-medium text-gray-700 mb-2">仪表盘数据</h4>
                    <pre id="plugin-detail-metrics" class="bg-gray-50 p-4 rounded-lg overflow-auto max-h-64 text-sm whitespace-pre-wrap text-gray-700">加载中...</pre>
                </div>
                <!-- API测试 tab -->
                <div id="plugin-tab-apitest" class="plugin-detail-content hidden">
                    <p class="text-sm text-gray-500 mb-3">直接调用插件注册的 API 路由查看返回结果(经机器人进程代理)</p>
                    <div class="grid grid-cols-1 md:grid-cols-12 gap-3 mb-3">
                        <div class="md:col-span-3">
                            <select id="plugin-api-method" onchange="document.getElementById('plugin-api-body-wrap').classList.toggle('hidden', this.value === 'GET')"
                                    class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500">
                                <option value="GET">GET</option>
                                <option value="POST">POST</option>
                            </select>
                        </div>
                        <div class="md:col-span-7">
                            <input type="text" id="plugin-api-path" placeholder="/stats 或 /top"
                                   class="w-full px-4 py-2 border border-gray-300 rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                        </div>
                        <div class="md:col-span-2">
                            <button onclick="testPluginApi()"
                                    class="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition">
                                <i class="fa fa-paper-plane mr-1"></i>发送
                            </button>
                        </div>
                    </div>
                    <div id="plugin-api-body-wrap" class="mb-3 hidden">
                        <label class="block text-sm font-medium text-gray-700 mb-1">请求体(JSON, 仅 POST)</label>
                        <textarea id="plugin-api-body" rows="4"
                                  class="w-full px-4 py-2 border border-gray-300 rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"></textarea>
                    </div>
                    <div class="text-sm text-gray-600 mb-2">已注册路由: <span id="plugin-api-routes-hint" class="text-blue-600 font-mono"></span></div>
                    <div class="text-sm text-gray-600 mb-2">响应:</div>
                    <pre id="plugin-api-result" class="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto max-h-64 text-xs whitespace-pre-wrap">(尚未发送请求)</pre>
                </div>
                <!-- 源码 tab -->
                <div id="plugin-tab-source" class="plugin-detail-content hidden">
                    <p class="text-sm text-gray-500 mb-3">在线编辑插件目录下实际存在的文本文件，保存前自动语法检查并备份</p>
                    <div class="mb-3">
                        <label class="block text-sm font-medium text-gray-700 mb-2">编辑文件</label>
                        <select id="plugin-source-file" onchange="updateSourceEditor()"
                                class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 max-w-full">
                            <option value="">加载中...</option>
                        </select>
                    </div>
                    <textarea id="plugin-source-editor" rows="20"
                              class="w-full px-4 py-3 border border-gray-300 rounded-lg font-mono text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"></textarea>
                    <div id="plugin-source-error" class="mt-2 text-sm text-red-600 hidden"></div>
                    <div class="mt-3 flex justify-end space-x-3">
                        <button onclick="savePluginSource()"
                                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center">
                            <i class="fa fa-save mr-2"></i>保存并重载
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<div id="edit-account-modal-global" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">全局关键词</h3>
            </div>
            <div class="bg-gray-50 rounded-lg p-4 mb-4">
                <h5 class="text-md font-medium text-gray-700 mb-3">添加新全局关键词</h5>
                <div class="space-y-4">
                    <div>
                        <input type="text" id="edit-account-keyword-input-global" 
                            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2focus:ring-primary-500 focus:border-primary-500 transition"
                            placeholder="关键词">
                    </div>
                    <div>
                        <textarea id="edit-account-reply-input-global" rows="4"
                            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition resize-vertical"
                            placeholder="请输入回复内容（支持换行）"></textarea>
                        </div>
                        <div>
                            <button type="button" onclick="showAddGlobalKeywordModal()"
                                class="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 focus:outline-nonfocus:ring-2 focus:ring-green-500 transition">
                                    <i class="fa fa-plus mr-1"></i>添加
                            </button>
                        </div>
                    </div>
                    <!-- 艾特用户提示 -->
                    <div class="mt-2 text-sm text-gray-600">
                        提示：在回复内容中使用 <code class="bg-gray-200 px-1 rounded">[at_user]</code> 来@用户，关键词处可使用<code class="bg-gray-200 px-1 rounded">;</code>分割关键词，用以达到使用多个关键词回复同一内容的功能
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="closeAddGlobalKeywordModal()"
                            class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            关闭
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
<!-- 修改关键词模态框 -->
<div id="edit-keyword-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-md">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">修改关键词</h3>
            </div>
            <div class="p-6">
                <form id="edit-keyword-form">
                    <input type="hidden" id="edit-original-keyword" name="original_keyword">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">关键词</label>
                            <input type="text" id="edit-keyword-input" name="keyword" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="请输入关键词">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">回复内容</label>
                            <textarea id="edit-reply-input" name="reply" rows="4" required
                                      class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition resize-vertical"
                                      placeholder="请输入回复内容（支持换行）"></textarea>
                        </div>
                        <div class="text-sm text-gray-600">
                            提示：在回复内容中使用 <code class="bg-gray-200 px-1 rounded">[at_user]</code> 来@用户，关键词处可使用<code class="bg-gray-200 px-1 rounded">;</code>分割关键词，用以达到使用多个关键词回复同一内容的功能
                        </div>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideEditKeywordModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            保存修改
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
<!-- GitHub配置模态框 -->
<div id="github-config-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">GitHub配置</h3>
            </div>
            <div class="p-6">
                <form id="github-config-form">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">GitHub Client ID</label>
                            <input type="text" name="client_id" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="输入GitHub OAuth App的Client ID">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">GitHub Client Secret</label>
                            <input type="password" name="client_secret" 
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="输入GitHub OAuth App的Client Secret">
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">仓库所有者</label>
                                <input type="text" name="repo_owner" value="7Hello80"
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 mb-2">仓库名称</label>
                                <input type="text" name="repo_name" value="Bilibili_PrivateMessage_Bot"
                                       class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition">
                            </div>
                        </div>
                        <div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
                            <h4 class="text-sm font-medium text-blue-800 mb-2">配置说明</h4>
                            <p class="text-sm text-blue-700 markdown-body">
                                1. 在GitHub设置中创建OAuth App<br>
                                2. Authorization callback URL填写: <code class="bg-blue-100 px-1 rounded">http://你的域名/github/callback</code><br>
                                3. 将获取的Client ID和Client Secret填入上方<br>
                                4. 教程：https://cloud.tencent.com/developer/article/1663102
                            </p>
                        </div>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideGitHubConfigModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            保存配置
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- 创建讨论模态框 -->
<div id="create-discussion-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-4xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <h3 class="text-xl font-bold text-gray-800">新建讨论</h3>
            </div>
            <div class="p-6">
                <form id="create-discussion-form">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">标题</label>
                            <input type="text" name="title" required
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="输入讨论标题">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">内容</label>
                            <textarea name="body" rows="10" required
                                      class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition resize-vertical"
                                      placeholder="输入讨论内容（支持Markdown格式）"></textarea>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">标签</label>
                            <input type="text" name="labels"
                                   class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition"
                                   placeholder="输入标签，多个标签用逗号分隔">
                            <p class="text-xs text-gray-500 mt-1">例如: bug, enhancement, question</p>
                        </div>
                    </div>
                    <div class="mt-6 flex justify-end space-x-3">
                        <button type="button" onclick="hideCreateDiscussionModal()"
                                class="px-4 py-2 text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 transition">
                            取消
                        </button>
                        <button type="submit"
                                class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                            发布讨论
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<!-- 讨论详情模态框 -->
<div id="discussion-detail-modal" class="fixed inset-0 bg-black bg-opacity-50 z-50 hidden">
    <div class="flex items-center justify-center min-h-screen p-4">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-6xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-gray-200">
                <div class="flex items-center justify-between">
                    <h3 class="text-xl font-bold text-gray-800" id="discussion-title"></h3>
                    <button onclick="hideDiscussionDetailModal()" class="p-2 hover:bg-gray-100 rounded-lg transition">
                        <i class="fa fa-times text-gray-600"></i>
                    </button>
                </div>
            </div>
            <div class="p-6">
                <div id="discussion-content" class="prose max-w-none mb-6">
                    <!-- 讨论内容将通过JS填充 -->
                </div>
                
                <div class="border-t border-gray-200 pt-6">
                    <h4 class="text-lg font-medium text-gray-800 mb-4">评论</h4>
                    <div id="comments-list" class="space-y-4 mb-6">
                        <!-- 评论列表将通过JS填充 -->
                    </div>
                    
                    <form id="create-comment-form" class="bg-gray-50 rounded-lg p-4">
                        <input type="hidden" id="current-discussion-number">
                        <div class="mb-4">
                            <label class="block text-sm font-medium text-gray-700 mb-2">发表评论</label>
                            <textarea name="body" rows="4" required
                                      class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 transition resize-vertical"
                                      placeholder="输入你的评论（支持Markdown格式）"></textarea>
                        </div>
                        <div class="flex justify-end">
                            <button type="submit"
                                    class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 transition">
                                发布评论
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
<script src="{{ url_for('static', filename='script.js') }}"></script>
{% endblock %}''')

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