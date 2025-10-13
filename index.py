# -*- coding: utf-8 -*-
import requests
import json
import time
import logging
import uuid
from typing import Dict, List, Optional, Set
import colorama
from colorama import Fore, Back, Style
import sys
import ConfigManage
import init
import os
import threading
import io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
else:
    # 对于旧版本，重新创建stdout流
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, 
        encoding='utf-8',
        errors='replace' if sys.stdout.errors == 'strict' else sys.stdout.errors,
        newline=sys.stdout.newlines,
        line_buffering=sys.stdout.line_buffering
    )

config = ConfigManage.ConfigManager("config.json")

# 初始化colorama
colorama.init(autoreset=True)

def clean_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

class BotManager:
    def __init__(self):
        self.bots = []
        self.running = False
        
    def start_all(self):
        """启动所有启用的机器人"""
        if self.running:
            return False
            
        self.running = True
        accounts = config.get_accounts()
        
        for i, account in enumerate(accounts):
            if account.get("enabled", True):
                bot = SimpleBilibiliReply(
                    account_name=account.get("name", f"账号{i+1}"),
                    sessdata=account["config"]["sessdata"],
                    bili_jct=account["config"]["bili_jct"],
                    self_uid=account["config"]["self_uid"],
                    device_id=account["config"]["device_id"],
                    keywords=account.get("keyword", {}),
                    at_user=account.get("at_user", False),
                    auto_focus=account.get("auto_focus", False),
                    poll_interval=5,
                )
                self.bots.append(bot)
                
                # 在新线程中启动机器人
                thread = threading.Thread(target=bot.run, daemon=True)
                thread.start()
                
        print(f"{Fore.GREEN}✓ 已启动 {len(self.bots)} 个机器人实例")
        return True
        
    def stop_all(self):
        """停止所有机器人"""
        self.running = False
        for bot in self.bots:
            bot.stop()
        self.bots.clear()
        print(f"{Fore.GREEN}✓ 已停止所有机器人实例")

class SimpleBilibiliReply:
    def __init__(self, account_name, sessdata, bili_jct, self_uid, device_id, keywords, at_user, auto_focus, poll_interval=5):
        self.account_name = account_name
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.self_uid = self_uid
        self.poll_interval = poll_interval
        self.running = False
        
        # 生成设备ID
        self.device_id = device_id
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://message.bilibili.com",
            "Referer": "https://message.bilibili.com/",
            "Cookie": f"SESSDATA={sessdata}; bili_jct={bili_jct}"
        }
        
        # 设置自动回复关键词（账号特定 + 全局）
        self.keyword_reply = keywords
        global_keywords = config.get_global_keywords()
        self.keyword_reply.update(global_keywords)
        
        self.at_user = at_user
        self.auto_focus = auto_focus
        
        self.processed_msg_ids = set()
        print(f"{Fore.GREEN}✓ {Fore.BLUE}[{self.account_name}] 哔哩哔哩私信自动回复机器人启动成功")
    
    def stop(self):
        """停止机器人"""
        self.running = False

    # 这里保留原有的所有方法，但修改日志输出以包含账号名称
    def get_sessions(self) -> List[Dict]:
        """获取会话列表"""
        url = "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions"
        params = {
            "session_type": 1,
            "group_fold": 1,
            "unfollow_fold": 0,
            "sort_rule": 2
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:
                    return data.get("data", {}).get("session_list", [])
                else:
                    print(f"{Fore.RED}✗ [{self.account_name}] API错误: {data.get('message')}")
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 获取会话列表异常: {e}")
        
        return []

    # 修改所有方法，在日志输出中添加 [账号名称] 前缀
    def Auto_focus(self, mid: int) -> Optional[Dict]:
        url = "https://api.bilibili.com/x/relation/modify"
        params = {
            "fid": mid,
            "act": 1,
            "csrf": self.bili_jct
        }
        try:
            response = requests.post(url, params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                if data.get("code") == 0:
                    return True
                else:
                    return False
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 关注失败: {e}")
        
        return None

    def get_userName(self, mid: int) -> Optional[Dict]:
        url = "https://api.bilibili.com/x/web-interface/card"
        params = {
            "mid": mid
        }
        
        try:
            response = requests.get(url, params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    print(f"{Fore.RED}✗ [{self.account_name}] 检索失败")
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 获取失败: {e}")
        
        return None

    def check_user_relation(self, target_uid: int) -> Optional[Dict]:
        url = "https://api.bilibili.com/x/web-interface/relation"
        params = {
            "mid": target_uid
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"{Fore.GREEN}✓ [{self.account_name}] 关系检查API响应: {Fore.MAGENTA}{json.dumps(data, ensure_ascii=False)}")
                
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    print(f"{Fore.RED}✗ [{self.account_name}] 关系检查API错误: {Fore.MAGENTA}{data.get('message')}")
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 检查用户关系异常: {Fore.MAGENTA}{e}")
        
        return None

    def is_following_me(self, target_uid: int) -> bool:
        relation_data = self.check_user_relation(target_uid)
        if not relation_data:
            return False
        
        relation = relation_data.get("be_relation", {})
        attribute = relation.get("attribute", 0)
        
        print(f"{Fore.MAGENTA}[{self.account_name}] 用户 {target_uid} 对我的关注状态: attribute={attribute}")
        
        if attribute in [2, 6]:
            print(f"{Fore.MAGENTA}[{self.account_name}] 用户 {target_uid} 已关注您")
            return True
        else:
            print(f"{Fore.RED}✗ [{self.account_name}] 用户 {target_uid} 未关注您")
            return False

    def extract_message_content(self, message_data: Dict) -> Optional[str]:
        """从消息数据中提取文本内容"""
        try:
            content = message_data.get("content", "")
            if not content:
                return None
                
            try:
                content_json = json.loads(content)
                return content_json.get("content", "")
            except json.JSONDecodeError:
                return content
        except Exception:
            return None

    def check_keywords(self, message: str) -> Optional[str]:
        """检查消息是否包含关键词"""
        if not message:
            return None
            
        lower_message = message.lower()
        
        for keyword, reply in self.keyword_reply.items():
            if keyword.lower() in lower_message:
                return reply
        
        return None

    def send_message(self, receiver_id: int, message: str) -> bool:
        """发送消息"""
        url = "https://api.vc.bilibili.com/web_im/v1/web_im/send_msg"
        
        timestamp = int(time.time())
        
        if self.at_user:
            userinfo = self.get_userName(receiver_id)
            content_json = {"content": message.replace("[at_user]", userinfo.get("card")["name"])}
        else:
            content_json = {"content": message}
        
        form_data = {
            'msg[sender_uid]': str(self.self_uid),
            'msg[receiver_type]': '1',
            'msg[receiver_id]': str(receiver_id),
            'msg[msg_type]': '1',
            'msg[msg_status]': '0',
            'msg[content]': json.dumps(content_json),
            'msg[new_face_version]': '0',
            'msg[canal_token]': '',
            'msg[dev_id]': self.device_id,
            'msg[timestamp]': str(timestamp),
            'from_firework': '0',
            'build': '0',
            'mobi_app': 'web',
            'csrf': self.bili_jct
        }
        
        params = {
            'w_sender_uid': str(self.self_uid),
            'w_receiver_id': str(receiver_id),
            'w_dev_id': self.device_id,
            'w_rid': self.generate_rid(),
            'wts': str(timestamp)
        }
        
        try:
            response = requests.post(
                url, 
                params=params,
                data=form_data, 
                headers=self.headers, 
                timeout=10
            )
            
            print(f"{Fore.GREEN}✓ [{self.account_name}] 发送消息响应状态: {Fore.MAGENTA}{response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"{Fore.GREEN}✓ [{self.account_name}] 发送消息响应内容: {Fore.MAGENTA}{data}")
                
                if data.get("code") == 0:
                    print(f"{Fore.GREEN}✓ [{self.account_name}] 成功发送消息给 {Fore.MAGENTA}{receiver_id}")
                    return True
                else:
                    print(f"{Fore.RED}✗ [{self.account_name}] 发送失败: {Fore.MAGENTA}{data.get('message')} (代码: {data.get('code')})")
                    if data.get("code") in [-400, 1000]:
                        return True
            else:
                print(f"{Fore.RED}✗ [{self.account_name}] HTTP错误: {Fore.MAGENTA}{response.status_code}")
                
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 发送消息异常: {Fore.MAGENTA}{e}")
        
        return False

    def generate_rid(self) -> str:
        """生成随机RID参数"""
        import hashlib
        import random
        import string
        
        random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        return hashlib.md5(random_str.encode()).hexdigest()

    def process_messages(self):
        """处理消息"""
        try:
            sessions = self.get_sessions()
            if not sessions:
                return
            
            for session in sessions:
                try:
                    talker_id = session.get("talker_id")
                    last_msg = session.get("last_msg", {})
                    
                    msg_id = last_msg.get("msg_seqno")
                    sender_uid = last_msg.get("sender_uid")
                    timestamp = last_msg.get("timestamp", 0)
                    receiver_id = last_msg.get("receiver_id")
                    
                    if sender_uid == int(self.self_uid):
                        continue
                    
                    if not msg_id or msg_id in self.processed_msg_ids:
                        continue
                    
                    current_time = int(time.time())
                    if current_time - timestamp > 300:
                        continue
                    
                    message_text = self.extract_message_content(last_msg)
                    if not message_text:
                        continue
                    
                    print(f"{Fore.GREEN}✓ [{self.account_name}] 收到来自 {Fore.MAGENTA}{talker_id} {Fore.GREEN}的消息: {Fore.MAGENTA}{message_text}")
                    
                    reply = self.check_keywords(message_text)
                    if reply:
                        if self.is_following_me(talker_id):
                            success = self.send_message(talker_id, reply)
                            
                            if self.auto_focus:
                                focus = self.Auto_focus(receiver_id)
                                if focus == True:
                                    print(f"{Fore.GREEN}✓ [{self.account_name}] 关注成功")
                                else:
                                    print(f"{Fore.RED}✗ [{self.account_name}] 关注失败，可能已关注对方")
                            
                            if success:
                                self.processed_msg_ids.add(msg_id)
                                print(f"{Fore.GREEN}✓ [{self.account_name}] 已处理消息 {Fore.MAGENTA}{msg_id}")
                            else:
                                print(f"{Fore.RED}✗ [{self.account_name}] 发送消息失败")
                        else:
                            print(f"{Fore.RED}✗ [{self.account_name}] 用户 {talker_id} 未关注您，不发送回复")
                            self.processed_msg_ids.add(msg_id)
                            self.send_message(talker_id, "你还没有点点关注哦~，白嫖可耻！")
                            
                    
                except Exception as e:
                    print(f"{Fore.RED}✗ [{self.account_name}] 处理会话异常: {Fore.MAGENTA}{e}")
                    continue
                    
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 处理消息主循环异常: {Fore.MAGENTA}{e}")

    def run(self):
        """运行监听"""
        print(f"{Fore.GREEN}✓ [{self.account_name}] 按 Ctrl+C 可停止运行\n")
        print(f"{Fore.GREEN}[{self.account_name}] 项目运行日志：")
        
        self.running = True
        try:
            while self.running:
                self.process_messages()
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            print(f"{Fore.GREEN}✓ [{self.account_name}] 用户手动停止程序")
        except Exception as e:
            print(f"{Fore.RED}✗ [{self.account_name}] 程序运行异常: {Fore.MAGENTA}{e}")
        finally:
            self.running = False

# 检查配置
def inspect_config():
    print(f"{Fore.BLUE}正在检查配置是否正确...")
    accounts = config.get_accounts()
    
    if not accounts:
        print(f"{Fore.RED}✗ 未找到任何账号配置")
        return False
    
    enabled_accounts = [acc for acc in accounts if acc.get("enabled", True)]
    
    if not enabled_accounts:
        print(f"{Fore.RED}✗ 没有启用的账号")
        return False
    
    print(f"{Fore.GREEN}✓ 找到 {len(enabled_accounts)} 个启用的账号")
    
    for i, account in enumerate(enabled_accounts):
        account_config = account["config"]
        print(f"{Fore.BLUE}检查账号 {i+1}: {account.get('name', '未命名')}")
        
        if not account_config.get("sessdata"):
            print(f"{Fore.RED}✗ SESSDATA未配置")
            return False
        if not account_config.get("bili_jct"):
            print(f"{Fore.RED}✗ BILI_JCT未配置")
            return False
        if not account_config.get("self_uid"):
            print(f"{Fore.RED}✗ SELF_UID未配置")
            return False
        if not account_config.get("device_id"):
            print(f"{Fore.RED}✗ DEVICE_ID未配置")
            return False
        
        print(f"{Fore.GREEN}✓ 账号配置正确")
    
    print(f"{Fore.GREEN}✓ 检查完成，开始运行\n")
    time.sleep(0.5)
    clean_screen()
    print(f"{Fore.GREEN}程序名称: {Fore.WHITE}哔哩哔哩私信机器人")
    print(f"{Fore.GREEN}版本号: {Fore.WHITE}v1.0.4")
    print(f"{Fore.GREEN}作者: {Fore.WHITE}淡意往事")
    print(f"{Fore.GREEN}哔哩哔哩主页: {Fore.WHITE}https://b23.tv/tq8hoKu")
    print(f"{Fore.GREEN}Github: {Fore.WHITE}https://github.com/7hello80")
    print(f"{Fore.GREEN}启动时间: {Fore.WHITE}{time.strftime('%Y-%m-%d %H:%M:%S')}")
    return True

if __name__ == "__main__":
    init.init_manage()
    is_config = inspect_config()
    if is_config:
        # 创建机器人管理器
        bot_manager = BotManager()
        
        try:
            # 启动所有机器人
            bot_manager.start_all()
            
            # 主线程保持运行
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            print(f"{Fore.GREEN}✓ 用户手动停止程序")
            bot_manager.stop_all()
    else:
        print(f"{Fore.RED}✗ 配置错误")