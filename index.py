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

init.init_manage()
config = ConfigManage.ConfigManager("config.json")

# 初始化colorama
colorama.init(autoreset=True)

SESSDATA = config.get("config")["sessdata"]
BILI_JCT = config.get("config")["bili_jct"]
SELF_UID = config.get("config")["self_uid"]
DEVICE_ID = config.get("config")["device_id"]

def clean_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

# 检查配置
def inspect_config():
    print(f"{Fore.BLUE}正在检查配置是否正确...")
    if SESSDATA == "":
        print(f"{Fore.RED}✗ {Fore.RED}SESSDATA未配置")
        return False
    
    print(f"{Fore.GREEN}✓ {Fore.BLUE}SESSDATA正确")
    
    if BILI_JCT == "":
        print(f"{Fore.RED}✗ {Fore.RED}BILI_JCT未配置")
        return False
    
    print(f"{Fore.GREEN}✓ {Fore.BLUE}BILI_JCT正确")
    
    if SELF_UID == 0:
        print(f"{Fore.RED}✗ {Fore.RED}SELF_UID未配置")
        return False
    
    print(f"{Fore.GREEN}✓ {Fore.BLUE}SELF_UID正确")
    
    if DEVICE_ID == "":
        print(f"{Fore.RED}✗ {Fore.RED}DEVICE_ID未配置")
        return False
    
    print(f"{Fore.GREEN}✓ {Fore.BLUE}DEVICE_ID正确")
    print(f"{Fore.GREEN}✓ {Fore.GREEN}检查完成，开始运行\n")
    time.sleep(0.5)
    clean_screen()
    return True

class SimpleBilibiliReply:
    def __init__(self, sessdata, bili_jct, self_uid, device_id, poll_interval=5):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.self_uid = self_uid
        self.poll_interval = poll_interval
        
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
        
        # 设置自动回复关键词
        self.keyword_reply = config.get("keyword")
        
        self.processed_msg_ids = set()
        print(f"{Fore.GREEN}✓ {Fore.BLUE}哔哩哔哩私信自动回复机器人启动成功")
        print(f"{Fore.GREEN}程序名称: {Fore.WHITE}哔哩哔哩私信机器人")
        print(f"{Fore.GREEN}版本号: {Fore.WHITE}v1.0.3")
        print(f"{Fore.GREEN}作者: {Fore.WHITE}淡意往事")
        print(f"{Fore.GREEN}哔哩哔哩主页: {Fore.WHITE}https://b23.tv/tq8hoKu")
        print(f"{Fore.GREEN}Github: {Fore.WHITE}https://github.com/7hello80")
        print(f"{Fore.GREEN}启动时间: {Fore.WHITE}{time.strftime('%Y-%m-%d %H:%M:%S')}")
    
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
                    print(f"{Fore.RED}✗ API错误: {data.get('message')}")
        except Exception as e:
            print(f"{Fore.RED}✗ 获取会话列表异常: {e}")
        
        return []

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
                    print(f"{Fore.RED}✗ 检索失败")
        except Exception as e:
            print(f"{Fore.RED}✗ 获取失败: {e}")
        
        return None

    # 查询对方是否关注了我
    def check_user_relation(self, target_uid: int) -> Optional[Dict]:
        url = "https://api.bilibili.com/x/web-interface/relation"
        params = {
            "mid": target_uid  # 目标用户的UID
        }
        
        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"{Fore.GREEN}✓ 关系检查API响应: {Fore.MAGENTA}{json.dumps(data, ensure_ascii=False)}")
                
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    print(f"{Fore.RED}✗ 关系检查API错误: {Fore.MAGENTA}{data.get('message')}")
        except Exception as e:
            print(f"{Fore.RED}✗ 检查用户关系异常: {Fore.MAGENTA}{e}")
        
        return None

    def is_following_me(self, target_uid: int) -> bool:
        relation_data = self.check_user_relation(target_uid)
        if not relation_data:
            return False
        
        # 获取目标用户对我的关系
        relation = relation_data.get("be_relation", {})
        attribute = relation.get("attribute", 0)
        
        print(f"{Fore.MAGENTA}用户 {target_uid} 对我的关注状态: attribute={attribute}")
        
        # 检查目标用户是否关注了我
        # attribute 为 2 或 6 表示关注了我
        if attribute in [2, 6]:
            print(f"{Fore.MAGENTA}用户 {target_uid} 已关注您")
            return True
        else:
            print(f"{Fore.RED}✗ 用户 {target_uid} 未关注您")
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
        config = ConfigManage.ConfigManager("config.json")
        self.keyword_reply = config.get("keyword")
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
        
        # 生成时间戳和随机参数
        timestamp = int(time.time())
        
        config = ConfigManage.ConfigManager("config.json")
        
        if config.get("at_user") == True:
            userinfo = self.get_userName(receiver_id)
            content_json = {"content": message.replace("[at_user]", userinfo.get("card")["name"])}
        else:
            content_json = {"content": message}
        
        # 构建表单数据（按照您提供的格式）
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
        
        # 构建URL参数
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
            
            print(f"{Fore.GREEN}✓ 发送消息响应状态: {Fore.MAGENTA}{response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"{Fore.GREEN}✓ 发送消息响应内容: {Fore.MAGENTA}{data}")
                
                if data.get("code") == 0:
                    print(f"{Fore.GREEN}✓ 成功发送消息给 {Fore.MAGENTA}{receiver_id}")
                    return True
                else:
                    print(f"{Fore.RED}✗ 发送失败: {Fore.MAGENTA}{data.get('message')} (代码: {data.get('code')})")
                    # 如果是消息重复发送错误，也标记为成功
                    if data.get("code") in [-400, 1000]:
                        return True
            else:
                print(f"{Fore.RED}✗ HTTP错误: {Fore.MAGENTA}{response.status_code}")
                
        except Exception as e:
            print(f"{Fore.RED}✗ 发送消息异常: {Fore.MAGENTA}{e}")
        
        return False

    def generate_rid(self) -> str:
        """生成随机RID参数"""
        import hashlib
        import random
        import string
        
        # 生成随机字符串
        random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        # 使用MD5生成哈希
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
                    
                    # 获取消息信息
                    msg_id = last_msg.get("msg_seqno")
                    sender_uid = last_msg.get("sender_uid")
                    timestamp = last_msg.get("timestamp", 0)
                    
                    # 跳过自己发送的消息
                    if sender_uid == int(self.self_uid):
                        continue
                    
                    # 检查是否已经处理过这条消息
                    if not msg_id or msg_id in self.processed_msg_ids:
                        continue
                    
                    # 只处理最近的消息
                    current_time = int(time.time())
                    if current_time - timestamp > 300:  # 5分钟
                        continue
                    
                    # 提取消息内容
                    message_text = self.extract_message_content(last_msg)
                    if not message_text:
                        continue
                    
                    print(f"{Fore.GREEN}✓ 收到来自 {Fore.MAGENTA}{talker_id} {Fore.GREEN}的消息: {Fore.MAGENTA}{message_text}")
                    
                    # 检查关键词
                    reply = self.check_keywords(message_text)
                    if reply:
                        # 检查对方是否关注了我
                        if self.is_following_me(talker_id):
                            success = self.send_message(talker_id, reply)
                            if success:
                                self.processed_msg_ids.add(msg_id)
                                print(f"{Fore.GREEN}✓ 已处理消息 {Fore.MAGENTA}{msg_id}")
                            else:
                                print(f"{Fore.RED}✗  发送消息失败")
                        else:
                            print(f"{Fore.RED}✗ 用户 {talker_id} 未关注您，不发送回复")
                            # 标记为已处理，避免重复检查
                            self.processed_msg_ids.add(msg_id)
                            self.send_message(talker_id, "你还没有点点关注哦~，白嫖可耻！")
                            
                    
                except Exception as e:
                    print(f"{Fore.RED}✗ 处理会话异常: {Fore.MAGENTA}{e}")
                    continue
                    
        except Exception as e:
            print(f"{Fore.RED}✗ 处理消息主循环异常: {Fore.MAGENTA}{e}")

    def run(self):
        """运行监听"""
        print(f"{Fore.GREEN}✓ 按 Ctrl+C 可停止运行\n")
        print(f"{Fore.GREEN}项目运行日志：")
        
        try:
            while True:
                self.process_messages()
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            print(f"{Fore.GREEN}✓ 用户手动停止程序")
        except Exception as e:
            print(f"{Fore.RED}✗ 程序运行异常: {Fore.MAGENTA}{e}")

if __name__ == "__main__":
    init.init_manage()
    is_config = inspect_config()
    if is_config:
        # 创建机器人实例
        bot = SimpleBilibiliReply(
            sessdata=SESSDATA,
            bili_jct=BILI_JCT,
            self_uid=SELF_UID,
            device_id=DEVICE_ID,
            poll_interval=5,
        )
        
        # 运行机器人
        bot.run()
    else:
        print(f"{Fore.RED}✗ 配置错误")