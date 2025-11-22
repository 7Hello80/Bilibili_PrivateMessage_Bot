import json
import os
import requests
import ConfigManage

# 部署统计
def tj():
    url = "https://apis.bzks.qzz.io/tj.php"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"请求失败: {e}")

def init_manage():
    if os.path.exists("config.json"):
        config_manager = ConfigManage.ConfigManager("config.json")
        config = config_manager.config
        
        # 检查并更新配置结构，而不是重置
        updated = False
        
        # 检查顶层结构
        if "accounts" not in config:
            config["accounts"] = [
                {
                    "name": "默认账号",
                    "config": {
                        "sessdata": "",
                        "bili_jct": "",
                        "self_uid": 0,
                        "device_id": ""
                    },
                    "keyword": {
                        "测试运行": "自动回复系统正常！"
                    },
                    "at_user": False,
                    "auto_focus": False,
                    "enabled": True
                }
            ]
            updated = True
            print("已添加缺失的 accounts 配置")
        
        if "global_keywords" not in config:
            config["global_keywords"] = {
                "测试运行": "自动回复系统正常！"
            }
            updated = True
            print("已添加缺失的 global_keywords 配置")
        
        if "images" not in config:
            config["images"] = []
            updated = True
            print("已添加缺失的 images 配置")
        
        # 检查每个账号的结构
        for i, account in enumerate(config.get("accounts", [])):
            account_updated = False
            
            # 检查账号基本字段
            if "name" not in account:
                account["name"] = f"账号{i+1}"
                account_updated = True
            
            if "config" not in account:
                account["config"] = {
                    "sessdata": "",
                    "bili_jct": "",
                    "self_uid": 0,
                    "device_id": ""
                }
                account_updated = True
            else:
                # 检查config内部的字段
                config_fields = account["config"]
                if "sessdata" not in config_fields:
                    config_fields["sessdata"] = ""
                    account_updated = True
                if "bili_jct" not in config_fields:
                    config_fields["bili_jct"] = ""
                    account_updated = True
                if "self_uid" not in config_fields:
                    config_fields["self_uid"] = 0
                    account_updated = True
                if "device_id" not in config_fields:
                    config_fields["device_id"] = ""
                    account_updated = True
            
            if "keyword" not in account:
                account["keyword"] = {}
                account_updated = True
            
            if "at_user" not in account:
                account["at_user"] = False
                account_updated = True
            
            if "auto_focus" not in account:
                account["auto_focus"] = False
                account_updated = True
            
            if "enabled" not in account:
                account["enabled"] = True
                account_updated = True
            
            if "auto_reply_follow" not in account:
                account["auto_reply_follow"] = False
                account_updated = True
            
            if "follow_reply_message" not in account:
                account["follow_reply_message"] = "感谢关注！"
                account_updated = True
            
            if "no_focus_hf" not in account:
                account["no_focus_hf"] = False
                account_updated = True
            
            if account_updated:
                updated = True
                print(f"已更新账号 {i+1} 的配置结构")
        
        # 如果配置有更新，保存配置
        if updated:
            config_manager.save_config()
            print("配置文件已更新到最新版本")
        else:
            print("配置文件结构正常！")
            
    else:
        # 配置文件不存在，创建默认配置
        config = {
            "accounts": [
                {
                    "name": "默认账号",
                    "config": {
                        "sessdata": "",
                        "bili_jct": "",
                        "self_uid": 0,
                        "device_id": ""
                    },
                    "keyword": {
                        "测试运行": "自动回复系统正常！"
                    },
                    "at_user": False,
                    "auto_focus": False,
                    "auto_reply_follow": False,  # 新增
                    "follow_reply_message": "感谢关注！",  # 新增
                    "no_focus_hf": False,
                    "enabled": True
                }
            ],
            "global_keywords": {
                "测试运行": "自动回复系统正常！"
            },
            "images": []
        }
        
        # 写入JSON文件
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        tj()
        print("系统初始化成功，已创建默认配置文件")