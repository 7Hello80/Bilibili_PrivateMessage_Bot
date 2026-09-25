import os
import re
import json
import time
import requests
import zipfile
import tempfile
import shutil
import py_compile
from typing import Dict, List, Any, Optional
import logging
from pathlib import Path
from plugin_loader import plugin_loader

PLUGIN_NAME_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


class PluginManager:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self.github_base_url = "https://api.github.com/repos"
        self.backup_dir = "plugin_backups"

        # 创建插件目录
        os.makedirs(plugins_dir, exist_ok=True)

    # ============ 名称安全 ============

    @staticmethod
    def sanitize_plugin_name(name: str) -> str:
        """净化插件名: 只允许字母数字下划线连字符, 无前缀时自动补 bilibot_plugins_"""
        name = str(name or '').strip()
        if not PLUGIN_NAME_RE.match(name):
            return ''
        if not name.startswith("bilibot_plugins_"):
            name = f"bilibot_plugins_{name}"
        return name

    @staticmethod
    def _safe_extract_zip(zip_path: str, dest_dir: str) -> bool:
        """安全解压 zip(防 zip-slip): 拒绝绝对路径/.. /符号链接, realpath 前缀校验"""
        try:
            dest_real = os.path.realpath(dest_dir)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for info in zf.infolist():
                    name = info.filename
                    # 拒绝绝对路径与 .. 穿越
                    if name.startswith('/') or '..' in name.replace('\\', '/'):
                        logging.error(f"zip 包含危险路径: {name}")
                        return False
                    # 拒绝符号链接
                    if info.external_attr & 0o170000 == 0o120000 or os.path.islink(os.path.join(dest_dir, name)):
                        logging.error(f"zip 包含符号链接: {name}")
                        return False
                    target = os.path.realpath(os.path.join(dest_dir, name))
                    if not target.startswith(dest_real + os.sep) and target != dest_real:
                        logging.error(f"zip 条目逃逸目标目录: {name}")
                        return False
                    if info.is_dir():
                        os.makedirs(target, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with zf.open(info) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
            return True
        except Exception as e:
            logging.error(f"安全解压失败: {str(e)}")
            return False

    # ============ 在线商店 ============

    def search_plugins(self, keyword: str = "", github_token: str = "") -> List[Dict[str, Any]]:
        """从GitHub搜索插件(有 token 时使用鉴权, 避免未认证限流)"""
        try:
            # 搜索 GitHub 上以 bilibot_plugins 开头的仓库
            q = f"bilibot_plugins_{keyword} in:name fork:true" if keyword else \
                "bilibot_plugins_ in:name fork:true"
            search_url = "https://api.github.com/search/repositories"
            params = {
                'q': q,
                'sort': 'stars',
                'order': 'desc',
                'per_page': 20
            }
            headers = {'Accept': 'application/vnd.github+json'}
            if github_token:
                headers['Authorization'] = f"token {github_token}"

            response = requests.get(search_url, params=params, headers=headers, timeout=15)
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
            elif response.status_code == 403:
                logging.error("GitHub 搜索被限流(未认证 10 次/分钟), 请检查 access_token 配置")
                return []
            else:
                logging.error(f"搜索插件失败: {response.status_code}")
                return []

        except Exception as e:
            logging.error(f"搜索插件时出错: {str(e)}")
            return []

    def get_plugin_package_info(self, repo_full_name: str, branch: str = None) -> Optional[Dict[str, Any]]:
        """获取插件的package.json信息(main 失败回退 master)"""
        branches = [branch] if branch else ['main', 'master']
        for b in branches:
            try:
                package_url = f"https://raw.githubusercontent.com/{repo_full_name}/{b}/package.json"
                response = requests.get(package_url, timeout=8)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict):
                        data.setdefault('_branch', b)
                        return data
            except:
                continue
        return None

    def _validate_downloaded_plugin(self, extracted_dir: str) -> Optional[str]:
        """校验解压后的插件目录: 结构 + 语法. 返回错误信息(无错误返回 None)"""
        package_json = os.path.join(extracted_dir, "package.json")
        main_py = os.path.join(extracted_dir, "main.py")
        if not os.path.exists(package_json) or not os.path.exists(main_py):
            return "插件缺少必要的文件 (package.json 或 main.py)"
        try:
            with open(package_json, 'r', encoding='utf-8') as f:
                package = json.load(f)
            if not package.get('name'):
                return "package.json 缺少 name 字段"
            if 'version' not in package:
                return "package.json 缺少 version 字段"
        except ValueError as e:
            return f"package.json 解析失败: {str(e)}"
        try:
            with open(main_py, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'class Plugin' not in content:
                return "main.py 中没有找到 Plugin 类"
            # 只编译不执行, 面板进程不运行插件代码
            py_compile.compile(main_py, doraise=True)
        except py_compile.PyCompileError as e:
            return f"main.py 语法错误: {str(e)}"
        except Exception as e:
            return f"main.py 读取失败: {str(e)}"
        return None

    def download_plugin(self, repo_full_name: str, plugin_name: str) -> bool:
        """下载并安装插件(含结构校验 + 语法检查, 只编译不执行)"""
        try:
            plugin_name = self.sanitize_plugin_name(plugin_name)
            if not plugin_name:
                logging.error("插件名不合法")
                return False

            # 下载ZIP文件(main 失败回退 master)
            response = None
            for branch in ['main', 'master']:
                zip_url = f"https://github.com/{repo_full_name}/archive/refs/heads/{branch}.zip"
                try:
                    response = requests.get(zip_url, stream=True, timeout=60)
                except Exception:
                    continue
                if response is not None and response.status_code == 200:
                    break

            if response is None or response.status_code != 200:
                logging.error(f"下载插件失败: {response.status_code if response else '网络错误'}")
                return False

            # 创建临时目录
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, f"{plugin_name}.zip")

                # 保存ZIP文件
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # 安全解压
                if not self._safe_extract_zip(zip_path, temp_dir):
                    return False

                # 找到解压后的目录
                extracted_dir = os.path.join(temp_dir, f"{repo_full_name.split('/')[1]}-main")
                if not os.path.isdir(extracted_dir):
                    extracted_dir = os.path.join(temp_dir, f"{repo_full_name.split('/')[1]}-master")
                if not os.path.isdir(extracted_dir):
                    # 回退: 找解压出的第一层唯一目录
                    subdirs = [d for d in os.listdir(temp_dir)
                               if os.path.isdir(os.path.join(temp_dir, d))]
                    if len(subdirs) == 1:
                        extracted_dir = os.path.join(temp_dir, subdirs[0])

                # 校验插件结构与语法
                error = self._validate_downloaded_plugin(extracted_dir)
                if error:
                    logging.error(f"插件校验失败: {error}")
                    return False

                # 自动补充 repository 字段
                try:
                    with open(os.path.join(extracted_dir, "package.json"), 'r', encoding='utf-8') as f:
                        package = json.load(f)
                    package.setdefault('repository', f"https://github.com/{repo_full_name}")
                    with open(os.path.join(extracted_dir, "package.json"), 'w', encoding='utf-8') as f:
                        json.dump(package, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass

                # 复制到插件目录
                plugin_dir = os.path.join(self.plugins_dir, plugin_name)
                if os.path.exists(plugin_dir):
                    shutil.rmtree(plugin_dir)

                shutil.copytree(extracted_dir, plugin_dir)

                logging.info(f"插件 {plugin_name} 下载安装成功")
                return True

        except Exception as e:
            logging.error(f"下载插件时出错: {str(e)}")
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

    def set_plugin_enabled(self, plugin_name: str, enabled: bool) -> bool:
        """原子写 package.json 的 enabled 字段(供面板使用; 机器人侧不写此文件)"""
        try:
            package_json_path = os.path.join(self.plugins_dir, plugin_name, "package.json")
            if not os.path.exists(package_json_path):
                logging.error(f"插件 {plugin_name} 的 package.json 不存在")
                return False
            with open(package_json_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            metadata['enabled'] = bool(enabled)
            tmp_path = package_json_path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, package_json_path)
            return True
        except Exception as e:
            logging.error(f"更新插件 {plugin_name} 启用状态失败: {str(e)}")
            return False

    def get_installed_plugins(self) -> List[Dict[str, Any]]:
        """获取已安装的插件列表(仅文件系统信息, 运行状态由面板合并 status 文件)"""
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
                    'loaded': False,  # 面板进程不加载插件, 真实状态由 web_panel 合并
                    'has_update': False,
                    'latest_version': None
                }
                plugins.append(plugin_info)
            except Exception as e:
                logging.error(f"获取插件 {plugin_name} 信息失败: {str(e)}")
                # 添加一个基础信息
                plugins.append({
                    'name': plugin_name,
                    'enabled': False,
                    'metadata': {'name': plugin_name, 'version': 'unknown'},
                    'loaded': False,
                    'has_update': False,
                    'latest_version': None
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
                'loaded': False,
                'path': plugin_path
            }
        except Exception as e:
            logging.error(f"获取插件 {plugin_name} 信息失败: {str(e)}")
            return None

    def check_plugin_update(self, plugin_name: str, github_token: str = "") -> Dict[str, Any]:
        """检查插件更新: 对比本地版本与远程仓库 package.json 版本"""
        result = {
            'has_update': False, 'local_version': None,
            'latest_version': None, 'latest_meta': None, 'message': ''
        }
        try:
            info = self.get_plugin_info(plugin_name)
            if not info:
                result['message'] = '插件不存在'
                return result
            metadata = info['metadata']
            result['local_version'] = metadata.get('version', '1.0.0')

            repo_full_name = metadata.get('repository', '')
            if not repo_full_name:
                result['message'] = '插件没有配置 repository 字段, 无法检查更新'
                return result
            # 从仓库地址提取 owner/repo
            repo_full_name = repo_full_name.strip()
            if repo_full_name.startswith('https://github.com/'):
                repo_full_name = repo_full_name[len('https://github.com/'):]
            if repo_full_name.endswith('.git'):
                repo_full_name = repo_full_name[:-4]

            branch = metadata.get('_branch')
            package_info = self.get_plugin_package_info(repo_full_name, branch)
            if not package_info:
                result['message'] = '无法获取远程 package.json(仓库不存在或无此文件)'
                return result

            latest_version = package_info.get('version')
            if not latest_version:
                result['message'] = '远程 package.json 缺少 version 字段'
                return result
            result['latest_version'] = latest_version
            result['latest_meta'] = package_info

            from plugin_dev import PluginUtils
            if PluginUtils.parse_version(latest_version) > PluginUtils.parse_version(result['local_version']):
                result['has_update'] = True
            else:
                result['message'] = '已是最新版本'
            return result

        except Exception as e:
            result['message'] = f'检查更新出错: {str(e)}'
            logging.error(f"检查插件 {plugin_name} 更新时出错: {str(e)}")
            return result

    def update_plugin(self, plugin_name: str, github_token: str = "") -> bool:
        """更新插件(备份后覆盖下载)"""
        try:
            check = self.check_plugin_update(plugin_name, github_token)
            if not check.get('has_update'):
                logging.error(f"插件 {plugin_name} 无可用更新")
                return False

            info = self.get_plugin_info(plugin_name)
            if not info:
                return False

            # 从metadata中获取仓库信息
            repo_full_name = info['metadata'].get('repository', '')
            if not repo_full_name:
                logging.error(f"插件 {plugin_name} 没有配置仓库地址")
                return False
            if repo_full_name.startswith('https://github.com/'):
                repo_full_name = repo_full_name[len('https://github.com/'):]
            if repo_full_name.endswith('.git'):
                repo_full_name = repo_full_name[:-4]

            # 备份旧版本后覆盖下载(保留 enabled 状态)
            old_enabled = info['metadata'].get('enabled', True)
            self.backup_plugin(plugin_name)
            if not self.download_plugin(repo_full_name, plugin_name):
                logging.error(f"插件 {plugin_name} 更新下载失败")
                return False
            self.set_plugin_enabled(plugin_name, old_enabled)

            logging.info(f"插件 {plugin_name} 更新成功")
            return True

        except Exception as e:
            logging.error(f"更新插件时出错: {str(e)}")
            return False

    def backup_plugin(self, plugin_name: str, backup_dir: str = "plugin_backups") -> Optional[str]:
        """备份插件(文件名带时间戳), 返回备份文件路径"""
        try:
            plugin_path = os.path.join(self.plugins_dir, plugin_name)
            if not os.path.exists(plugin_path):
                return None

            os.makedirs(backup_dir, exist_ok=True)
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f"{plugin_name}_{timestamp}.zip")

            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(plugin_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, plugin_path)
                        zipf.write(file_path, arcname)

            logging.info(f"插件 {plugin_name} 备份成功: {backup_path}")
            return backup_path

        except Exception as e:
            logging.error(f"备份插件时出错: {str(e)}")
            return None

    def list_backups(self, plugin_name: str) -> List[Dict[str, Any]]:
        """列出插件的备份文件(按时间倒序)"""
        try:
            if not os.path.exists(self.backup_dir):
                return []
            backups = []
            prefix = f"{plugin_name}_"
            for fname in os.listdir(self.backup_dir):
                if fname.startswith(prefix) and fname.endswith('.zip'):
                    fpath = os.path.join(self.backup_dir, fname)
                    stat = os.stat(fpath)
                    backups.append({
                        'file': fname,
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'time_str': time.strftime('%Y-%m-%d %H:%M:%S',
                                                  time.localtime(stat.st_mtime))
                    })
            backups.sort(key=lambda x: x['mtime'], reverse=True)
            return backups
        except Exception as e:
            logging.error(f"列出插件 {plugin_name} 备份失败: {str(e)}")
            return []

    def restore_plugin(self, plugin_name: str, backup_file: str) -> bool:
        """从备份恢复插件(恢复前自动备份当前版本)"""
        try:
            backup_path = os.path.join(self.backup_dir, os.path.basename(backup_file))
            if not os.path.exists(backup_path):
                logging.error(f"备份文件不存在: {backup_file}")
                return False

            plugin_dir = os.path.join(self.plugins_dir, plugin_name)

            # 恢复到临时目录并校验
            with tempfile.TemporaryDirectory() as temp_dir:
                if not self._safe_extract_zip(backup_path, temp_dir):
                    return False
                extracted_dir = os.path.join(temp_dir, plugin_name)
                if not os.path.isdir(extracted_dir):
                    # 备份 zip 的条目是平铺的, 直接在 temp_dir 下
                    extracted_dir = temp_dir
                error = self._validate_downloaded_plugin(extracted_dir)
                if error:
                    logging.error(f"备份内容校验失败: {error}")
                    return False

                # 自动备份当前版本(防止恢复失败)
                if os.path.exists(plugin_dir):
                    self.backup_plugin(plugin_name)
                    shutil.rmtree(plugin_dir)

                shutil.copytree(extracted_dir, plugin_dir)

            logging.info(f"插件 {plugin_name} 从备份 {backup_file} 恢复成功")
            return True

        except Exception as e:
            logging.error(f"恢复插件 {plugin_name} 时出错: {str(e)}")
            return False

    def import_plugin_zip(self, zip_path: str) -> tuple:
        """本地导入插件 zip. 返回 (是否成功, 插件名/错误信息)"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                if not self._safe_extract_zip(zip_path, temp_dir):
                    return False, "zip 解压失败(含不安全路径)"

                # 找到插件根目录(zip 内可能有一层包裹目录)
                root_dir = temp_dir
                entries = [d for d in os.listdir(temp_dir)
                           if os.path.isdir(os.path.join(temp_dir, d))]
                if len(entries) == 1 and not os.path.exists(os.path.join(temp_dir, "package.json")):
                    root_dir = os.path.join(temp_dir, entries[0])

                if not os.path.exists(os.path.join(root_dir, "package.json")):
                    return False, "zip 中没有找到 package.json"

                with open(os.path.join(root_dir, "package.json"), 'r', encoding='utf-8') as f:
                    package = json.load(f)
                raw_name = package.get('name', '') or os.path.basename(root_dir)
                plugin_name = self.sanitize_plugin_name(raw_name)
                if not plugin_name:
                    return False, f"插件名不合法: {raw_name}"

                error = self._validate_downloaded_plugin(root_dir)
                if error:
                    return False, error

                plugin_dir = os.path.join(self.plugins_dir, plugin_name)
                if os.path.exists(plugin_dir):
                    return False, f"插件 {plugin_name} 已存在, 请先卸载再导入"

                shutil.copytree(root_dir, plugin_dir)
                logging.info(f"插件 {plugin_name} 本地导入成功")
                return True, plugin_name

        except Exception as e:
            logging.error(f"导入插件时出错: {str(e)}")
            return False, str(e)

# 全局插件管理器实例
plugin_manager = PluginManager()