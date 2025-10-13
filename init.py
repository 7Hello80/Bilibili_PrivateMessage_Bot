import json
import os
import requests

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
        print("配置文件正常！")
    else:
        # 配置数据 - 多账号结构
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
                    "enabled": True
                }
            ],
            "global_keywords": {
                "测试运行": "自动回复系统正常！"
            }
        }
        
        # 写入JSON文件
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        tj()
        print("系统初始化成功")