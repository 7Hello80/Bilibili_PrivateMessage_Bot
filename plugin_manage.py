import os
import json
import requests
import zipfile
import tempfile
import shutil
from typing import Dict, List, Any, Optional
import logging
from pathlib import Path
from plugin_loader import plugin_loader

class PluginManager:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self.github_base_url = "https://api.github.com/repos"
        
        # 创建插件目录
        os.makedirs(plugins_dir, exist_ok=True)
    
    def search_plugins(self, keyword: str = "") -> List[Dict[str, Any]]:
        """从GitHub搜索插件"""
        try:
            # 这里可以扩展为从多个源搜索
            # 目前只搜索GitHub上以bilibot_开头、_plugins结尾的仓库
            search_url = f"https://api.github.com/search/repositories"
            params = {
                'q': f'bilibot_plugins_{keyword} in:name fork:true',
                'sort': 'stars',
                'order': 'desc'
            }
            
            response = requests.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                plugins = []
                
                for repo in data.get('items', []):
                    plugin_info = {
                        'name': repo['name'],
                        'full_name': repo['full_name'],
                        'description': repo['description'],
                        'html_url': repo['html_url'],
                        'clone_url': repo['clone_url'],
                        'stars': repo['stargazers_count'],
                        'forks': repo['forks_count'],
                        'updated_at': repo['updated_at'],
                        'author': repo['owner']['login']
                    }
                    
                    # 尝试获取package.json信息
                    package_info = self.get_plugin_package_info(repo['full_name'])
                    if package_info:
                        plugin_info.update(package_info)
                    
                    plugins.append(plugin_info)
                
                return plugins
            else:
                logging.error(f"搜索插件失败: {response.status_code}")
                return []
                
        except Exception as e:
            logging.error(f"搜索插件时出错: {str(e)}")
            return []
    
    def get_plugin_package_info(self, repo_full_name: str) -> Optional[Dict[str, Any]]:
        """获取插件的package.json信息"""
        try:
            package_url = f"https://raw.githubusercontent.com/{repo_full_name}/main/package.json"
            response = requests.get(package_url, timeout=5)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None
    
    def download_plugin(self, repo_full_name: str, plugin_name: str) -> bool:
        """下载并安装插件"""
        try:
            # 下载ZIP文件
            zip_url = f"https://github.com/{repo_full_name}/archive/refs/heads/main.zip"
            response = requests.get(zip_url, stream=True, timeout=30)
            
            if response.status_code == 200:
                # 创建临时目录
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, f"{plugin_name}.zip")
                    
                    # 保存ZIP文件
                    with open(zip_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # 解压ZIP文件
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    # 找到解压后的目录
                    extracted_dir = os.path.join(temp_dir, f"{repo_full_name.split('/')[1]}-main")
                    
                    # 检查必要的文件
                    if not (os.path.exists(os.path.join(extracted_dir, "package.json")) and 
                            os.path.exists(os.path.join(extracted_dir, "main.py"))):
                        logging.error("插件缺少必要的文件 (package.json 或 main.py)")
                        return False
                    
                    # 复制到插件目录
                    plugin_dir = os.path.join(self.plugins_dir, plugin_name)
                    if os.path.exists(plugin_dir):
                        shutil.rmtree(plugin_dir)
                    
                    shutil.copytree(extracted_dir, plugin_dir)
                    
                    logging.info(f"插件 {plugin_name} 下载安装成功")
                    return True
            else:
                logging.error(f"下载插件失败: {response.status_code}")
                print(18)
                return False
                
        except Exception as e:
            logging.error(f"下载插件时出错: {str(e)}")
            print(19)
            return False
    
    def delete_plugin(self, plugin_name: str) -> bool:
        """删除插件"""
        try:
            plugin_dir = os.path.join(self.plugins_dir, plugin_name)
            if os.path.exists(plugin_dir):
                # 先卸载插件
                plugin_loader.unload_plugin(plugin_name)
                # 删除目录
                shutil.rmtree(plugin_dir)
                logging.info(f"插件 {plugin_name} 删除成功")
                return True
            else:
                logging.error(f"插件 {plugin_name} 不存在")
                return False
        except Exception as e:
            logging.error(f"删除插件时出错: {str(e)}")
            return False
    
    def get_installed_plugins(self) -> List[Dict[str, Any]]:
        """获取已安装的插件列表"""
        plugins = []
        plugin_names = plugin_loader.discover_plugins()
        
        for plugin_name in plugin_names:
            try:
                plugin_path = os.path.join(self.plugins_dir, plugin_name)
                package_json_path = os.path.join(plugin_path, "package.json")
                
                with open(package_json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                plugin_info = {
                    'name': plugin_name,
                    'enabled': metadata.get('enabled', True),
                    'metadata': metadata,
                    'loaded': plugin_name in plugin_loader.plugins and plugin_loader.plugins[plugin_name].instance is not None
                }
                plugins.append(plugin_info)
            except Exception as e:
                logging.error(f"获取插件 {plugin_name} 信息失败: {str(e)}")
                # 添加一个基础信息
                plugins.append({
                    'name': plugin_name,
                    'enabled': False,
                    'metadata': {'name': plugin_name, 'version': 'unknown'},
                    'loaded': False
                })
        
        return plugins
    
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """获取插件详细信息"""
        try:
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            package_json_path = os.path.join(plugin_path, "package.json")
            
            with open(package_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            return {
                'name': plugin_name,
                'enabled': metadata.get('enabled', True),
                'metadata': metadata,
                'loaded': plugin_name in plugin_loader.plugins and plugin_loader.plugins[plugin_name].instance is not None,
                'path': plugin_path
            }
        except Exception as e:
            logging.error(f"获取插件 {plugin_name} 信息失败: {str(e)}")
            return None
    
    def update_plugin(self, plugin_name: str) -> bool:
        """更新插件"""
        try:
            plugin_info = self.get_plugin_info(plugin_name)
            if not plugin_info:
                return False
            
            # 从metadata中获取仓库信息
            repo_full_name = plugin_info['metadata'].get('repository', '')
            if not repo_full_name:
                logging.error(f"插件 {plugin_name} 没有配置仓库地址")
                return False
            
            # 删除旧版本并重新下载
            if self.delete_plugin(plugin_name):
                # 从仓库地址提取repo_full_name
                if repo_full_name.startswith('https://github.com/'):
                    repo_full_name = repo_full_name[19:]  # 移除 'https://github.com/'
                    if repo_full_name.endswith('.git'):
                        repo_full_name = repo_full_name[:-4]
                
                return self.download_plugin(repo_full_name, plugin_name)
            
            return False
            
        except Exception as e:
            logging.error(f"更新插件时出错: {str(e)}")
            return False
    
    def backup_plugin(self, plugin_name: str, backup_dir: str = "plugin_backups") -> bool:
        """备份插件"""
        try:
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            if not os.path.exists(plugin_path):
                return False
            
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"{plugin_name}.zip")
            
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(plugin_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, plugin_path)
                        zipf.write(file_path, arcname)
            
            logging.info(f"插件 {plugin_name} 备份成功: {backup_path}")
            return True
            
        except Exception as e:
            logging.error(f"备份插件时出错: {str(e)}")
            return False

# 全局插件管理器实例
plugin_manager = PluginManager()