import json
import os
from typing import Any, Dict, List

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            return {}
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def save_config(self):
        """保存配置到文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
    
    def get(self, key: str, default=None):
        """获取配置值"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self.config[key] = value
        self.save_config()
    
    def delete(self, key: str):
        """删除配置项"""
        if key in self.config:
            del self.config[key]
            self.save_config()
    
    def get_accounts(self) -> List[Dict]:
        """获取所有账号"""
        return self.config.get("accounts", [])
    
    def get_account(self, index: int) -> Dict:
        """获取指定索引的账号"""
        accounts = self.get_accounts()
        if 0 <= index < len(accounts):
            return accounts[index]
        return {}
    
    def add_account(self, account: Dict):
        """添加账号"""
        accounts = self.get_accounts()
        accounts.append(account)
        self.set("accounts", accounts)
    
    def update_account(self, index: int, account: Dict):
        """更新账号"""
        accounts = self.get_accounts()
        if 0 <= index < len(accounts):
            accounts[index] = account
            self.set("accounts", accounts)
    
    def delete_account(self, index: int):
        """删除账号"""
        accounts = self.get_accounts()
        if 0 <= index < len(accounts):
            accounts.pop(index)
            self.set("accounts", accounts)
    
    def get_global_keywords(self) -> Dict:
        """获取全局关键词"""
        return self.config.get("global_keywords", {})
    
    def set_global_keywords(self, keywords: Dict):
        """设置全局关键词"""
        self.set("global_keywords", keywords)
    
    def get_account_keywords(self, account_index: int) -> Dict:
        """获取指定账号的关键词"""
        account = self.get_account(account_index)
        return account.get("keyword", {})
    
    def set_account_keywords(self, account_index: int, keywords: Dict):
        """设置指定账号的关键词"""
        account = self.get_account(account_index)
        if account:
            account["keyword"] = keywords
            self.update_account(account_index, account)
    
    def add_account_keyword(self, account_index: int, keyword: str, reply: str):
        """为指定账号添加关键词"""
        keywords = self.get_account_keywords(account_index)
        keywords[keyword] = reply
        self.set_account_keywords(account_index, keywords)
    
    def delete_account_keyword(self, account_index: int, keyword: str):
        """删除指定账号的关键词"""
        keywords = self.get_account_keywords(account_index)
        if keyword in keywords:
            del keywords[keyword]
            self.set_account_keywords(account_index, keywords)