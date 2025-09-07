import requests
import json
import time
import logging
import uuid
from typing import Dict, List, Optional, Set

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bilibili_auto_reply.log"),
        logging.StreamHandler()
    ]
)

class SimpleBilibiliReply:
    def __init__(self, sessdata, bili_jct, self_uid, poll_interval=5, device_id):
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
        self.keyword_reply = {
            "创意工坊": "网站地址：https://steam.bzks.qzz.io\n说明：支持系统默认账号和个人账号登陆，可实时查看任务执行日志，可解析游戏的创意工坊内容，前提是使用的账号已购买该游戏，不然无法进行解析\n(机器人系统自动回复)"
        }
        
        self.processed_msg_ids = set()
        logging.info(f"================================================")
        logging.info(f"B站自动回复机器人初始化完成，用户UID: {self_uid}")

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
                    logging.warning(f"API错误: {data.get('message')}")
        except Exception as e:
            logging.error(f"获取会话列表异常: {e}")
        
        return []

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
                logging.debug(f"关系检查API响应: {json.dumps(data, ensure_ascii=False)}")
                
                if data.get("code") == 0:
                    return data.get("data", {})
                else:
                    logging.warning(f"关系检查API错误: {data.get('message')}")
        except Exception as e:
            logging.error(f"检查用户关系异常: {e}")
        
        return None

    def is_following_me(self, target_uid: int) -> bool:
        relation_data = self.check_user_relation(target_uid)
        if not relation_data:
            return False
        
        # 获取目标用户对我的关系
        relation = relation_data.get("be_relation", {})
        attribute = relation.get("attribute", 0)
        
        logging.debug(f"用户 {target_uid} 对我的关注状态: attribute={attribute}")
        
        # 检查目标用户是否关注了我
        # attribute 为 2 或 6 表示关注了我
        if attribute in [2, 6]:
            logging.info(f"用户 {target_uid} 已关注您")
            return True
        else:
            logging.info(f"用户 {target_uid} 未关注您")
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
        
        # 生成时间戳和随机参数
        timestamp = int(time.time())
        
        # 构建消息内容
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
            
            logging.debug(f"发送消息响应状态: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logging.debug(f"发送消息响应内容: {data}")
                
                if data.get("code") == 0:
                    logging.info(f"✓ 成功发送消息给 {receiver_id}")
                    return True
                else:
                    logging.warning(f"发送失败: {data.get('message')} (代码: {data.get('code')})")
                    # 如果是消息重复发送错误，也标记为成功
                    if data.get("code") in [-400, 1000]:
                        return True
            else:
                logging.warning(f"HTTP错误: {response.status_code}")
                
        except Exception as e:
            logging.error(f"发送消息异常: {e}")
        
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
                    if sender_uid == self.self_uid:
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
                    
                    logging.info(f"收到来自 {talker_id} 的消息: {message_text}")
                    
                    # 检查关键词
                    reply = self.check_keywords(message_text)
                    if reply:
                        # 检查对方是否关注了我
                        if self.is_following_me(talker_id):
                            success = self.send_message(talker_id, reply)
                            if success:
                                self.processed_msg_ids.add(msg_id)
                                logging.info(f"✓ 已处理消息 {msg_id}")
                            else:
                                logging.warning(f"✗ 发送消息失败")
                        else:
                            logging.info(f"用户 {talker_id} 未关注您，不发送回复")
                            # 标记为已处理，避免重复检查
                            self.processed_msg_ids.add(msg_id)
                            self.send_message(talker_id, "你还没有点点关注哦~，白嫖可耻！")
                    
                except Exception as e:
                    logging.error(f"处理会话异常: {e}")
                    continue
                    
        except Exception as e:
            logging.error(f"处理消息主循环异常: {e}")

    def run(self):
        """运行监听"""
        logging.info("B站私信自动回复机器人已启动")
        logging.info("按 Ctrl+C 可停止运行")
        logging.info(f"================================================")
        
        try:
            while True:
                self.process_messages()
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            logging.info("用户手动停止程序")
        except Exception as e:
            logging.error(f"程序运行异常: {e}")

if __name__ == "__main__":
    # 更改为你的
    SESSDATA = "" # sessdata
    BILI_JCT = "" # bili_jct
    SELF_UID = 123456789  # 你的UID
    DEVICE_ID = ""
    
    # 创建机器人实例
    bot = SimpleBilibiliReply(
        sessdata=SESSDATA,
        bili_jct=BILI_JCT,
        self_uid=SELF_UID,
        poll_interval=5,
        device_id=DEVICE_ID
    )
    
    # 运行机器人
    bot.run()