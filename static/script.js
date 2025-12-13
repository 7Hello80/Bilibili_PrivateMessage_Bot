let layuiForm = null;
// 插件商店功能
let currentPluginSearchKeyword = '';
let installedPlugins = [];
let onlinePlugins = [];

// 配置marked选项（如果还没有配置的话）
if (typeof marked !== 'undefined') {
    marked.setOptions({
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                try {
                    return hljs.highlight(lang, code).value;
                } catch (err) {
                    console.error('代码高亮错误:', err);
                }
            }
            return hljs.highlightAuto(code).value;
        },
        langPrefix: 'hljs language-',
        breaks: true,
        gfm: true,
        tables: true
    });
}

// 初始化 Layui 表单
function initLayuiForm() {
    layui.use('form', function(){
        layuiForm = layui.form;
        layuiForm.render();
    });
}

// 全局变量
let currentPreviewUrl = '';

// 移动端菜单控制
document.addEventListener('DOMContentLoaded', function() {
    // 为所有移动端菜单按钮添加事件监听
    const menuButtons = document.querySelectorAll('#mobile-menu-button, .mobile-menu-button');
    menuButtons.forEach(button => {
        button.addEventListener('click', function() {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('overlay');
            if (sidebar && overlay) {
                sidebar.classList.toggle('-translate-x-full');
                overlay.style.display = sidebar.classList.contains('-translate-x-full') ? 'none' : 'block';
            }
        });
    });

    const overlay = document.getElementById('overlay');
    if (overlay) {
        overlay.addEventListener('click', function() {
            const sidebar = document.getElementById('sidebar');
            if (sidebar) {
                sidebar.classList.add('-translate-x-full');
                this.style.display = 'none';
            }
        });
    }
});

// 显示插件商店页面
function showPluginsSection() {
    showSection('plugins');
    loadInstalledPlugins();
}

// 加载已安装插件
function loadInstalledPlugins() {
    fetch('/api/plugins/list')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                installedPlugins = data.plugins;
                updateInstalledPluginsList();
            } else {
                showNotification('加载插件列表失败', 'error');
            }
        })
        .catch(error => {
            console.error('加载插件列表失败:', error);
            showNotification('加载插件列表失败', 'error');
        });
}

// 更新已安装插件列表
function updateInstalledPluginsList() {
    const container = document.getElementById('installed-plugins-list');
    if (!container) return;

    if (!installedPlugins || installedPlugins.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <i class="fa fa-puzzle-piece text-3xl mb-3"></i>
                <p>暂无安装的插件</p>
                <p class="text-sm mt-2">在插件市场中搜索并安装插件</p>
            </div>
        `;
        return;
    }

    container.innerHTML = installedPlugins.map(plugin => `
        <div class="border border-gray-200 rounded-lg p-4 mb-4 bg-white hover:bg-gray-50 transition">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center space-x-3">
                    <div class="w-3 h-3 rounded-full ${plugin.enabled ? 'bg-green-500' : 'bg-gray-400'}"></div>
                    <h4 class="text-lg font-medium text-gray-800">${plugin.metadata.name}</h4>
                    <span class="text-sm px-2 py-1 bg-blue-100 text-blue-800 rounded">v${plugin.metadata.version}</span>
                    ${plugin.loaded ? '<span class="text-sm px-2 py-1 bg-green-100 text-green-800 rounded">已加载</span>' : ''}
                </div>
                <div class="flex items-center space-x-2">
                    <button onclick="togglePlugin('${plugin.name}', ${!plugin.enabled})" 
                            class="px-3 py-1 text-sm ${plugin.enabled ? 'bg-yellow-600 hover:bg-yellow-700' : 'bg-green-600 hover:bg-green-700'} text-white rounded transition">
                        ${plugin.enabled ? '禁用' : '启用'}
                    </button>
                    <button onclick="reloadPlugin('${plugin.name}')" 
                            class="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded transition">
                        重载
                    </button>
                    <button onclick="uninstallPlugin('${plugin.name}')" 
                            class="px-3 py-1 text-sm bg-red-600 hover:bg-red-700 text-white rounded transition">
                        卸载
                    </button>
                </div>
            </div>
            
            <div class="text-sm text-gray-600 mb-3">
                ${plugin.metadata.description || '暂无描述'}
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                    <span class="text-gray-600">作者:</span>
                    <span class="ml-2 font-medium">${plugin.metadata.author || '未知'}</span>
                </div>
                <div>
                    <span class="text-gray-600">类型:</span>
                    <span class="ml-2 font-medium">${plugin.metadata.type || 'base'}</span>
                </div>
                <div>
                    <span class="text-gray-600">加载顺序:</span>
                    <span class="ml-2 font-medium">${plugin.metadata.load_order || 0}</span>
                </div>
            </div>
            
            ${plugin.metadata.dependencies && plugin.metadata.dependencies.length > 0 ? `
            <div class="mt-3 pt-3 border-t border-gray-200">
                <h5 class="text-sm font-medium text-gray-700 mb-2">依赖:</h5>
                <div class="flex flex-wrap gap-1">
                    ${plugin.metadata.dependencies.map(dep => `
                        <span class="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs">${dep}</span>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        </div>
    `).join('');
}

// 搜索插件
function searchPlugins() {
    const keyword = document.getElementById('plugin-search').value;
    currentPluginSearchKeyword = keyword;
    
    if (!keyword.trim()) {
        document.getElementById('online-plugins-list').innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <p>在搜索框中输入关键词搜索插件</p>
            </div>
        `;
        return;
    }

    document.getElementById('online-plugins-list').innerHTML = `
        <div class="text-center text-gray-500 py-8">
            <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
            <p>搜索中...</p>
        </div>
    `;

    fetch(`/api/plugins/search?keyword=${encodeURIComponent(keyword)}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                onlinePlugins = data.plugins;
                updateOnlinePluginsList();
            } else {
                showNotification('搜索插件失败', 'error');
                document.getElementById('online-plugins-list').innerHTML = `
                    <div class="text-center text-gray-500 py-8">
                        <p>搜索失败</p>
                    </div>
                `;
            }
        })
        .catch(error => {
            console.error('搜索插件失败:', error);
            showNotification('搜索插件失败', 'error');
        });
}

// 更新在线插件列表
function updateOnlinePluginsList() {
    const container = document.getElementById('online-plugins-list');
    if (!container) return;

    if (!onlinePlugins || onlinePlugins.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <p>没有找到相关插件</p>
            </div>
        `;
        return;
    }

    container.innerHTML = onlinePlugins.map(plugin => {
        const isInstalled = installedPlugins.some(p => p.name === plugin.name);
        
        return `
        <div class="border border-gray-200 rounded-lg p-4 mb-4 bg-white hover:bg-gray-50 transition">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center space-x-3">
                    <h4 class="text-lg font-medium text-gray-800">${plugin.name}</h4>
                    <span class="text-sm px-2 py-1 bg-blue-100 text-blue-800 rounded">v${plugin.version || '1.0.0'}</span>
                    ${isInstalled ? '<span class="text-sm px-2 py-1 bg-green-100 text-green-800 rounded">已安装</span>' : ''}
                </div>
                <div class="flex items-center space-x-2">
                    ${!isInstalled ? `
                    <button onclick="installPlugin('${plugin.full_name}', '${plugin.name}')" 
                            class="px-3 py-1 text-sm bg-green-600 hover:bg-green-700 text-white rounded transition">
                        安装
                    </button>
                    ` : ''}
                    <a href="${plugin.html_url}" target="_blank" 
                       class="px-3 py-1 text-sm bg-gray-600 hover:bg-gray-700 text-white rounded transition">
                        查看
                    </a>
                </div>
            </div>
            
            <div class="text-sm text-gray-600 mb-3">
                ${plugin.description || '暂无描述'}
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 text-sm">
                <div>
                    <span class="text-gray-600">作者:</span>
                    <span class="ml-2 font-medium">${plugin.author || plugin.owner || '未知'}</span>
                </div>
                <div>
                    <span class="text-gray-600">星标:</span>
                    <span class="ml-2 font-medium">${plugin.stars || 0}</span>
                </div>
                <div>
                    <span class="text-gray-600"> forks:</span>
                    <span class="ml-2 font-medium">${plugin.forks || 0}</span>
                </div>
                <div>
                    <span class="text-gray-600">更新:</span>
                    <span class="ml-2 font-medium">${formatDate(plugin.updated_at)}</span>
                </div>
            </div>
            
            ${plugin.dependencies && plugin.dependencies.length > 0 ? `
            <div class="mt-3 pt-3 border-t border-gray-200">
                <h5 class="text-sm font-medium text-gray-700 mb-2">依赖:</h5>
                <div class="flex flex-wrap gap-1">
                    ${plugin.dependencies.map(dep => `
                        <span class="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs">${dep}</span>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        </div>
        `;
    }).join('');
}

function getPluginList() {
    document.getElementById('online-plugins-list').innerHTML = `
        <div class="text-center text-gray-500 py-8">
            <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
            <p>加载中...</p>
        </div>
    `;
    fetch(`/api/plugins/lists`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                onlinePlugins = data.plugins;
                updateOnlinePluginsList();
            } else {
                showNotification('获取插件失败', 'error');
                document.getElementById('online-plugins-list').innerHTML = `
                    <div class="text-center text-gray-500 py-8">
                        <p>获取失败</p>
                    </div>
                `;
            }
        })
        .catch(error => {
            console.error('获取插件失败:', error);
            showNotification('获取插件失败', 'error');
        });
}

// 安装插件
function installPlugin(repoFullName, pluginName) {
    layer.confirm(`确定要安装插件 "${pluginName}" 吗？`, {
        icon: 3,
        title: '确认安装'
    }, function(index) {
        fetch('/api/plugins/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                repo_full_name: repoFullName,
                plugin_name: pluginName
            })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                loadInstalledPlugins();
                // 重新搜索以更新安装状态
                if (currentPluginSearchKeyword) {
                    searchPlugins();
                }
            }
        })
        .catch(error => {
            console.error('安装插件失败:', error);
            showNotification('安装插件失败', 'error');
        });
        layer.close(index);
    });
}

// 卸载插件
function uninstallPlugin(pluginName) {
    layer.confirm(`确定要卸载插件 "${pluginName}" 吗？此操作不可恢复！`, {
        icon: 3,
        title: '确认卸载'
    }, function(index) {
        fetch('/api/plugins/uninstall', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin_name: pluginName })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                loadInstalledPlugins();
                // 重新搜索以更新安装状态
                if (currentPluginSearchKeyword) {
                    searchPlugins();
                }
            }
        })
        .catch(error => {
            console.error('卸载插件失败:', error);
            showNotification('卸载插件失败', 'error');
        });
        layer.close(index);
    });
}

// 启用/禁用插件
function togglePlugin(pluginName, enable) {
    fetch('/api/plugins/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            plugin_name: pluginName,
            enabled: enable
        })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            loadInstalledPlugins();
        }
    })
    .catch(error => {
        console.error('切换插件状态失败:', error);
        showNotification('切换插件状态失败', 'error');
    });
}

// 重新加载插件
function reloadPlugin(pluginName) {
    fetch('/api/plugins/reload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            loadInstalledPlugins();
        }
    })
    .catch(error => {
        console.error('重新加载插件失败:', error);
        showNotification('重新加载插件失败', 'error');
    });
}

// 格式化日期
function formatDate(dateString) {
    if (!dateString) return '未知';
    const date = new Date(dateString);
    return date.toLocaleDateString();
}

// 创建插件模态框
function showCreatePluginModal() {
    document.getElementById('create-plugin-modal').classList.remove('hidden');
}

function hideCreatePluginModal() {
    document.getElementById('create-plugin-modal').classList.add('hidden');
}

// 创建插件表单提交
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('plugin-search');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchPlugins();
            }
        });
    }

    const createPluginForm = document.getElementById('create-plugin-form');
    if (createPluginForm) {
        createPluginForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            const pluginData = {
                name: formData.get('name'),
                type: formData.get('type'),
                author: formData.get('author'),
                description: formData.get('description'),
                version: formData.get('version')
            };
            
            fetch('/api/plugins/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(pluginData)
            })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    hideCreatePluginModal();
                    this.reset();
                    loadInstalledPlugins();
                }
            })
            .catch(error => {
                console.error('创建插件失败:', error);
                showNotification('创建插件失败', 'error');
            });
        });
    }
});

// 显示指定部分，隐藏其他部分
function showSection(sectionId) {
    // 隐藏所有部分
    document.querySelectorAll('.section').forEach(section => {
        section.style.display = 'none';
    });
    
    // 显示选中的部分
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.style.display = 'block';
    }
    
    // 更新导航项状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active', 'bg-primary-50', 'border', 'border-primary-100', 'text-gray-700');
        item.classList.add('text-gray-600', 'hover:bg-gray-50');
    });
    
    // 找到被点击的导航项并激活它
    const clickedNav = document.querySelector(`[href="#${sectionId}"]`);
    if (clickedNav) {
        clickedNav.classList.add('active', 'bg-primary-50', 'border', 'border-primary-100', 'text-gray-700');
        clickedNav.classList.remove('text-gray-600', 'hover:bg-gray-50');
    }

    // 特殊处理：如果是日志部分，开始轮询日志
    if (sectionId === 'logs') {
        startLogPolling();
    } else {
        stopLogPolling();
    }
    
    // 在移动端选择后关闭菜单
    if (window.innerWidth < 1024) {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('overlay');
        if (sidebar) sidebar.classList.add('-translate-x-full');
        if (overlay) overlay.style.display = 'none';
    }
}

// 启动日志轮询
function startLogPolling() {
    if (window.logInterval) clearInterval(window.logInterval);
    fetchLogs();
    window.logInterval = setInterval(fetchLogs, 2000);
}

// 停止日志轮询
function stopLogPolling() {
    if (window.logInterval) {
        clearInterval(window.logInterval);
        window.logInterval = null;
    }
}

// 日志相关的全局变量
let currentLogFilter = 'all';
let currentLogs = [];
let autoScrollEnabled = true;

// 设置日志过滤器
function setLogFilter(filter) {
    currentLogFilter = filter;
    
    // 更新按钮状态
    document.querySelectorAll('.log-filter-btn').forEach(btn => {
        btn.classList.remove('active', 'bg-blue-600', 'text-white');
        btn.classList.add('bg-gray-200', 'text-gray-700');
    });
    
    const activeBtn = document.getElementById(`filter-${filter}`);
    if (activeBtn) {
        activeBtn.classList.add('active', 'bg-blue-600', 'text-white');
        activeBtn.classList.remove('bg-gray-200', 'text-gray-700');
    }
    
    // 重新渲染日志
    renderLogs();
}

// 过滤日志
function filterLogs() {
    renderLogs();
}

// 渲染日志
function renderLogs() {
    const logContainer = document.getElementById('log-container');
    const searchInput = document.getElementById('log-search');
    const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
    
    if (!logContainer) return;
    
    if (!currentLogs || currentLogs.length === 0) {
        logContainer.innerHTML = '<div class="text-center text-gray-500 py-8">暂无日志</div>';
        updateLogStats(0, 0);
        return;
    }
    
    let filteredLogs = currentLogs;
    
    // 应用类型过滤器
    if (currentLogFilter !== 'all') {
        filteredLogs = currentLogs.filter(log => {
            if (currentLogFilter === 'info') {
                return !log.includes('ERROR') && !log.includes('错误') && !log.includes('WARNING') && !log.includes('警告') && !log.includes('BOT:');
            } else if (currentLogFilter === 'warning') {
                return log.includes('WARNING') || log.includes('警告');
            } else if (currentLogFilter === 'error') {
                return log.includes('ERROR') || log.includes('错误') || log.includes('失败');
            } else if (currentLogFilter === 'bot') {
                return log.includes('BOT:');
            }
            return true;
        });
    }
    
    // 应用搜索过滤器
    if (searchTerm) {
        filteredLogs = filteredLogs.filter(log => log.toLowerCase().includes(searchTerm));
    }
    
    if (filteredLogs.length === 0) {
        logContainer.innerHTML = '<div class="text-center text-gray-500 py-8">没有匹配的日志</div>';
        updateLogStats(0, filteredLogs.length);
        return;
    }
    
    // 渲染日志条目
    logContainer.innerHTML = filteredLogs.map(log => {
        let logClass = 'info';
        let icon = 'fa fa-info-circle text-blue-400';
        let badge = '';
        
        if (log.includes('ERROR') || log.includes('错误') || log.includes('失败')) {
            logClass = 'error';
            icon = 'fa fa-exclamation-circle text-red-400';
        } else if (log.includes('成功') || log.includes('SUCCESS')) {
            logClass = 'success';
            icon = 'fa fa-check-circle text-green-400';
        } else if (log.includes('警告') || log.includes('WARNING')) {
            logClass = 'warning';
            icon = 'fa fa-exclamation-triangle text-yellow-400';
        } else if (log.includes('BOT:')) {
            logClass = 'bot';
            icon = 'fa fa-robot text-purple-400';
        }
        
        // 高亮搜索关键词
        let highlightedLog = log;
        if (searchTerm) {
            const regex = new RegExp(`(${searchTerm})`, 'gi');
            highlightedLog = log.replace(regex, '<mark class="bg-yellow-300 text-gray-900">$1</mark>');
        }
        
        return `
            <div class="log-entry ${logClass} flex items-start space-x-3 py-2 px-3 border-l-4 ${getBorderColor(logClass)} hover:bg-gray-800 transition cursor-pointer" onclick="copyLogContent('${log.replace(/'/g, "\'")}')">
                <i class="${icon} mt-1 flex-shrink-0"></i>
                <div class="flex-1">
                    <div class="flex items-center flex-wrap">
                        <span class="text-gray-300">${highlightedLog}</span>
                        ${badge}
                    </div>
                    <div class="text-xs text-gray-500 mt-1 opacity-0 hover:opacity-100 transition">
                        点击复制日志内容
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    updateLogStats(currentLogs.length, filteredLogs.length);
    
    // 自动滚动到底部
    if (autoScrollEnabled) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}

// 获取边框颜色
function getBorderColor(logClass) {
    switch(logClass) {
        case 'error': return 'border-red-500';
        case 'success': return 'border-green-500';
        case 'warning': return 'border-yellow-500';
        case 'bot': return 'border-purple-500';
        default: return 'border-blue-500';
    }
}

// 更新日志统计
function updateLogStats(total, displayed) {
    const displayedCount = document.getElementById('displayed-logs-count');
    const totalDisplayed = document.getElementById('total-displayed-logs');
    
    if (displayedCount) displayedCount.textContent = displayed;
    if (totalDisplayed) totalDisplayed.textContent = total;
    
    // 更新类型统计
    if (currentLogs && currentLogs.length > 0) {
        const infoCount = currentLogs.filter(log => 
            !log.includes('ERROR') && !log.includes('错误') && !log.includes('WARNING') && !log.includes('警告') && !log.includes('BOT:')
        ).length;
        const warningCount = currentLogs.filter(log => 
            log.includes('WARNING') || log.includes('警告')
        ).length;
        const errorCount = currentLogs.filter(log => 
            log.includes('ERROR') || log.includes('错误') || log.includes('失败')
        ).length;
        
        const totalCount = document.getElementById('total-logs-count');
        const infoCountEl = document.getElementById('info-logs-count');
        const warningCountEl = document.getElementById('warning-logs-count');
        const errorCountEl = document.getElementById('error-logs-count');
        
        if (totalCount) totalCount.textContent = currentLogs.length;
        if (infoCountEl) infoCountEl.textContent = infoCount;
        if (warningCountEl) warningCountEl.textContent = warningCount;
        if (errorCountEl) errorCountEl.textContent = errorCount;
    }
}

// 复制日志内容
function copyLogContent(content) {
    // 检查 clipboard API 是否可用
    if (!navigator.clipboard) {
        // 回退方案
        fallbackCopyTextToClipboard(content);
        return;
    }
    
    navigator.clipboard.writeText(content).then(() => {
        showNotification('日志内容已复制到剪贴板', 'success');
    }).catch(err => {
        console.error('复制失败:', err);
        // 尝试回退方案
        fallbackCopyTextToClipboard(content);
    });
}

// 图床管理功能
function showImageBedSection() {
    showSection('image_bed');
    loadImages();
}

// 图片上传功能
document.addEventListener('DOMContentLoaded', function() {
    const uploadForm = document.getElementById('upload-image-form');
    const fileInput = document.getElementById('image-file');
    const uploadArea = document.getElementById('upload-area');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    const uploadProgress = document.getElementById('upload-progress');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const uploadButton = document.getElementById('upload-button');

    // 加载上传账号列表
    function loadUploadAccounts() {
        fetch('/api/get_accounts')
            .then(response => response.json())
            .then(data => {
                if (data.accounts) {
                    const select = document.getElementById('upload-account');
                    select.innerHTML = '';
                    
                    let hasValidAccount = false;
                    
                    data.accounts.forEach((account, index) => {
                        if (account.enabled && account.config.sessdata && account.config.bili_jct) {
                            const option = document.createElement('option');
                            option.value = index;
                            option.textContent = `${account.name} (UID: ${account.config.self_uid})`;
                            select.appendChild(option);
                            hasValidAccount = true;
                        }
                    });
                    
                    if (!hasValidAccount) {
                        select.innerHTML = '<option value="">没有可用的账号</option>';
                        document.getElementById('upload-button').disabled = true;
                        showNotification('没有找到可用的B站账号，请先配置有效的SESSDATA和bili_jct', 'warning');
                    }
                    
                    // 重新渲染 Layui 选择器
                    if (layuiForm) {
                        layuiForm.render('select');
                    }
                }
            })
            .catch(error => {
                console.error('加载账号列表失败:', error);
                const select = document.getElementById('upload-account');
                select.innerHTML = '<option value="">加载失败，请刷新页面</option>';
                if (layuiForm) {
                    layuiForm.render('select');
                }
            });
    }

    loadUploadAccounts();

    uploadArea.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('border-blue-400', 'bg-blue-50');
    });

    uploadArea.addEventListener('dragenter', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('border-blue-400', 'bg-blue-50');
    });

    uploadArea.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        // 只有当鼠标离开上传区域时才移除样式
        if (!uploadArea.contains(e.relatedTarget)) {
            uploadArea.classList.remove('border-blue-400', 'bg-blue-50');
        }
    });

    uploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('border-blue-400', 'bg-blue-50');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            // 处理拖拽的文件
            handleFileSelect(files[0]);
            
            // 同时更新file input，确保表单数据一致
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(files[0]);
            fileInput.files = dataTransfer.files;
        }
    });

    // 点击上传
    uploadArea.addEventListener('click', function() {
        fileInput.click();
    });

    fileInput.addEventListener('change', function() {
        if (this.files.length > 0) {
            handleFileSelect(this.files[0]);
        } else {
            // 如果没有选择文件，重置状态
            resetFileSelection();
        }
    });

    function handleFileSelect(file) {
        if (!file) {
            showNotification('未选择文件', 'error');
            return;
        }

        // 检查文件类型
        const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
        if (!file.type.startsWith('image/') || !allowedTypes.includes(file.type.toLowerCase())) {
            showNotification('请选择有效的图片文件（JPG、PNG、GIF、WebP）', 'error');
            resetFileSelection();
            return;
        }

        // 检查文件大小（限制为10MB）
        const maxSize = 10 * 1024 * 1024; // 10MB
        if (file.size > maxSize) {
            showNotification('图片大小不能超过10MB', 'error');
            resetFileSelection();
            return;
        }

        if (file.size === 0) {
            showNotification('文件为空，请选择有效的图片文件', 'error');
            resetFileSelection();
            return;
        }

        // 显示文件信息
        fileName.textContent = file.name;
        fileSize.textContent = formatFileSize(file.size);
        fileInfo.classList.remove('hidden');

        // 检查是否有可用的账号
        const accountSelect = document.getElementById('upload-account');
        if (accountSelect && accountSelect.value === "") {
            showNotification('请先选择上传账号', 'error');
            uploadButton.disabled = true;
        } else {
            uploadButton.disabled = false;
        }
    }

    function resetFileSelection() {
        document.getElementById('file-info').classList.add('hidden');
        document.getElementById('upload-button').disabled = true;
        document.getElementById('image-file').value = '';
        document.getElementById('upload-area').classList.remove('border-blue-400', 'bg-blue-50');
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // 账号选择变化时启用/禁用上传按钮
    const accountSelect = document.getElementById('upload-account');
    if (accountSelect) {
        accountSelect.addEventListener('change', function() {
            const hasFile = fileInput.files.length > 0;
            if (this.value !== "" && hasFile) {
                uploadButton.disabled = false;
            } else {
                uploadButton.disabled = true;
            }
        });
    }

    // 表单提交
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const file = fileInput.files[0];
        const accountSelect = document.getElementById('upload-account');
        const accountIndex = accountSelect ? accountSelect.value : "";
        
        if (!file) {
            showNotification('请选择要上传的图片', 'error');
            return;
        }
        
        if (accountIndex === "") {
            showNotification('请选择上传账号', 'error');
            return;
        }

        uploadImage(file, accountIndex);
    });

    function uploadImage(file, accountIndex) {
        const formData = new FormData();
        formData.append('file_up', file);
        formData.append('account_index', accountIndex);

        // 显示上传进度
        document.getElementById('upload-progress').classList.remove('hidden');
        document.getElementById('upload-button').disabled = true;
        document.getElementById('progress-bar').style.width = '0%';
        document.getElementById('progress-text').textContent = '准备上传... 0%';

        const xhr = new XMLHttpRequest();
        
        // 监听上传进度
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 100);
                document.getElementById('progress-bar').style.width = percentComplete + '%';
                document.getElementById('progress-text').textContent = `上传中... ${percentComplete}%`;
            }
        });
        
        // 监听加载完成
        xhr.addEventListener('load', function() {
            if (xhr.status === 200) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    
                    if (response.code === 0) {
                        document.getElementById('progress-bar').style.width = '100%';
                        document.getElementById('progress-text').textContent = '上传完成';
                        
                        setTimeout(() => {
                            showLayuiAlert('图片上传成功', 'success');
                            
                            // 重置表单
                            resetFileSelection();
                            document.getElementById('upload-progress').classList.add('hidden');
                            
                            // 重新加载图片列表
                            loadImages();
                        }, 500);
                    } else {
                        handleUploadError(`上传失败: ${response.message || '未知错误'}`);
                    }
                } catch (e) {
                    handleUploadError('上传失败: 响应解析错误');
                }
            } else {
                handleUploadError(`上传失败: HTTP ${xhr.status}`);
            }
        });

        // 监听错误
        xhr.addEventListener('error', function() {
            handleUploadError('上传失败: 网络错误');
        });

        // 监听中止
        xhr.addEventListener('abort', function() {
            handleUploadError('上传已取消', 'warning');
        });

        // 打开连接并发送
        xhr.open('POST', '/api/upload_bfs');
        xhr.send(formData);
        
        // 添加取消按钮
        addCancelButton(xhr);
    }
    
    function handleUploadError(message, type = 'error') {
        document.getElementById('progress-bar').style.width = '100%';
        document.getElementById('progress-bar').classList.add('bg-red-600');
        document.getElementById('progress-text').textContent = '上传失败';
        showLayuiAlert(message, type);
        document.getElementById('upload-button').disabled = false;
        
        // 移除取消按钮
        const cancelBtn = document.getElementById('cancel-upload-btn');
        if (cancelBtn) {
            cancelBtn.remove();
        }
    }
    
    function resetUploadForm() {
        uploadForm.reset();
        resetFileSelection();
        uploadProgress.classList.add('hidden');
        uploadButton.disabled = true;
        
        // 移除取消按钮
        const cancelBtn = document.getElementById('cancel-upload-btn');
        if (cancelBtn) {
            cancelBtn.remove();
        }
    }
    
    // 添加上传取消功能
    function addCancelButton(xhr) {
        // 移除现有的取消按钮
        const existingCancelBtn = document.getElementById('cancel-upload-btn');
        if (existingCancelBtn) {
            existingCancelBtn.remove();
        }
        
        // 创建取消按钮
        const cancelBtn = document.createElement('button');
        cancelBtn.id = 'cancel-upload-btn';
        cancelBtn.type = 'button';
        cancelBtn.className = 'px-4 py-3 bg-gray-500 text-white rounded-lg hover:bg-gray-600 transition-all duration-200 shadow-sm hover:shadow-md';
        cancelBtn.innerHTML = '<i class="fa fa-times"></i>';
        
        cancelBtn.addEventListener('click', function() {
            if (xhr) {
                xhr.abort();
            }
        });
        
        // 插入取消按钮
        document.getElementById('upload-button').parentNode.appendChild(cancelBtn);
        
        // 上传完成后移除取消按钮
        xhr.addEventListener('loadend', function() {
            setTimeout(() => {
                if (cancelBtn.parentNode) {
                    cancelBtn.remove();
                }
            }, 1000);
        });
    }
});

// 加载图片列表
function loadImages() {
    fetch('/api/get_images')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateImagesList(data.images);
            } else {
                showLayuiAlert(data.message || '加载图片失败', 'error');
            }
        })
        .catch(error => {
            console.error('加载图片列表失败:', error);
            showLayuiAlert('加载图片列表失败', 'error');
        });
}

function updateImagesList(images) {
    const container = document.getElementById('images-list');
    const emptyMessage = document.getElementById('empty-images');
    const imagesCount = document.getElementById('images-count');
    
    if (!container) return;
    
    imagesCount.textContent = images ? images.length : 0;
    
    if (!images || images.length === 0) {
        container.classList.add('hidden');
        emptyMessage.classList.remove('hidden');
        return;
    }
    
    container.classList.remove('hidden');
    emptyMessage.classList.add('hidden');
    
    container.innerHTML = images.map((image, index) => `
        <div class="group relative bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-all duration-200">
            <div class="aspect-square bg-gray-100 overflow-hidden">
                <img src="${image.url}" 
                     alt="${image.name || '图片'}" 
                     class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105 cursor-pointer"
                     onclick="previewImage(${JSON.stringify(image).replace(/"/g, '&quot;')})"
                     loading="lazy"
                     onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjNmNGY2Ii8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzljYTNkYiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWbvueJh+WKoOi9veWksei0pTwvdGV4dD48L3N2Zz4='" referrerpolicy="no-referrer">
            </div>
            
            <div class="p-3">
                <p class="text-sm font-medium text-gray-800 truncate" title="${image.name || '未命名'}">
                    ${image.name || '未命名'}
                </p>
                <p class="text-xs text-gray-500 mt-1 truncate">
                    ${image.upload_account || '未知用户'}
                </p>
                <p class="text-xs text-gray-400 mt-1">
                    ${image.upload_time || ''}
                </p>
            </div>
            
            <!-- 悬停操作按钮 -->
            <div class="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-20 transition-all duration-200 flex items-center justify-center opacity-0 group-hover:opacity-100">
                <div class="flex space-x-2">
                    <button onclick="copyImageUrl('${image.url}')" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="复制URL">
                        <i class="fa fa-copy text-gray-700 text-sm"></i>
                    </button>
                    <button onclick="previewImage(${JSON.stringify(image).replace(/"/g, '&quot;')})" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="预览">
                        <i class="fa fa-eye text-blue-600 text-sm"></i>
                    </button>
                    <button onclick="deleteImage('${image.url}')" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="删除">
                        <i class="fa fa-trash text-red-600 text-sm"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function showLayuiAlert(message, type = 'info') {
    layui.use('layer', function(){
        const layer = layui.layer;
        const icon = type === 'success' ? 1 : 
                    type === 'error' ? 2 : 
                    type === 'warning' ? 3 : 0;
        
        layer.msg(message, { icon: icon });
    });
}

function initImageBed() {
    initLayuiForm();
    initializeImageUpload();
    loadImages();
}

// 右键菜单功能
function showImageContextMenu(event, imageUrl) {
    event.preventDefault();
    
    // 移除现有的右键菜单
    const existingMenu = document.getElementById('image-context-menu');
    if (existingMenu) {
        existingMenu.remove();
    }
    
    // 创建右键菜单
    const contextMenu = document.createElement('div');
    contextMenu.id = 'image-context-menu';
    contextMenu.className = 'fixed bg-white shadow-lg rounded-lg py-2 z-50 border border-gray-200';
    contextMenu.style.left = event.pageX + 'px';
    contextMenu.style.top = event.pageY + 'px';
    
    contextMenu.innerHTML = `
        <button onclick="copyImageUrl('${imageUrl}'); hideContextMenu()" 
                class="w-full px-4 py-2 text-left hover:bg-gray-100 flex items-center">
            <i class="fa fa-copy mr-2 text-blue-600"></i>复制URL
        </button>
        <hr class="my-1">
        <button onclick="deleteImage('${imageUrl}'); hideContextMenu()" 
                class="w-full px-4 py-2 text-left hover:bg-gray-100 flex items-center text-red-600">
            <i class="fa fa-trash mr-2"></i>删除图片
        </button>
    `;
    
    document.body.appendChild(contextMenu);
    
    // 点击其他地方隐藏菜单
    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
    }, 100);
}

function hideContextMenu() {
    const contextMenu = document.getElementById('image-context-menu');
    if (contextMenu) {
        contextMenu.remove();
    }
}

async function copyImageUrl(url) {
    const imageTag = `[bili_image:${url}]`;
    try {
        await navigator.clipboard.writeText(imageTag);
        showLayuiAlert('图片URL已复制到剪贴板', 'success');
    } catch (err) {
        console.error('复制失败:', err);
        showLayuiAlert('复制失败，请手动复制', 'error');
    }
}

// 图片上传功能优化
function initializeImageUpload() {
    const uploadForm = document.getElementById('upload-image-form');
    const fileInput = document.getElementById('image-file');
    const uploadArea = document.getElementById('upload-area');
    
    // 拖拽上传事件
    ['dragover', 'dragenter'].forEach(event => {
        uploadArea.addEventListener(event, (e) => {
            e.preventDefault();
            uploadArea.classList.add('border-blue-400', 'bg-blue-50');
        });
    });

    ['dragleave', 'dragend'].forEach(event => {
        uploadArea.addEventListener(event, (e) => {
            e.preventDefault();
            if (!uploadArea.contains(e.relatedTarget)) {
                uploadArea.classList.remove('border-blue-400', 'bg-blue-50');
            }
        });
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('border-blue-400', 'bg-blue-50');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(files[0]);
            fileInput.files = dataTransfer.files;
        }
    });

    // 点击上传
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFileSelect(fileInput.files[0]);
        } else {
            resetFileSelection();
        }
    });

    // 表单提交
    uploadForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const file = fileInput.files[0];
        const accountIndex = document.getElementById('upload-account').value;
        
        if (!file) {
            showLayuiAlert('请选择要上传的图片', 'warning');
            return;
        }
        
        if (!accountIndex) {
            showLayuiAlert('请选择上传账号', 'warning');
            return;
        }

        uploadImage(file, accountIndex);
    });
}

// 初始化代码高亮
function initCodeHighlighting() {
    // 配置highlight.js
    hljs.configure({
        tabReplace: '    ', // 4 spaces
        classPrefix: 'hljs-',
        languages: [
            // 编程语言
            'python', 'javascript', 'typescript', 'java', 'cpp', 'csharp', 'php', 'ruby',
            'go', 'rust', 'sql', 'swift', 'kotlin', 'scala', 'dart', 'r', 'matlab',
            'perl', 'lua', 'haskell', 'elixir', 'clojure', 'erlang', 'fortran', 'vbnet',
            'objectivec',
            
            // 配置和脚本语言
            'dockerfile', 'nginx', 'apache', 'makefile', 'cmake', 'gradle', 'groovy',
            'powershell', 'shell', 'bash', 'vim', 'ini', 'toml',
            
            // 标记和数据语言
            'html', 'css', 'xml', 'json', 'yaml', 'markdown', 'latex',
            
            // 其他
            'diff', 'plaintext'
        ]
    });
    
    // 高亮所有代码块
    document.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightElement(block);
    });
    document.querySelectorAll('.markdown-body pre code:not([class*="language-"])').forEach((block) => {
        if (!block.className.includes('hljs') && !block.className.includes('language-')) {
            const result = hljs.highlightAuto(block.textContent);
            block.innerHTML = result.value;
            block.className = 'hljs';
        }
    });
}

// 增强Markdown渲染函数
function renderMarkdownWithHighlight(markdownText) {
    // 使用marked解析Markdown
    const html = marked.parse(markdownText || '');
    
    // 返回HTML并确保代码块有合适的类名
    return html.replace(/<pre><code class="([^"]*)">/g, '<pre><code class="hljs $1">');
}

// 在页面加载完成后初始化代码高亮
document.addEventListener('DOMContentLoaded', function() {
    initCodeHighlighting();
    
    
});

function addLineNumbers(codeBlock) {
    const preElement = codeBlock.parentElement;
    
    // 如果已经添加了行号，跳过
    if (preElement.querySelector('.line-numbers')) {
        return;
    }
    
    // 获取代码行数
    const code = codeBlock.textContent || '';
    const lines = code.split('\\n');
    const lineCount = lines.length;
    
    // 创建行号容器
    const lineNumbersContainer = document.createElement('div');
    lineNumbersContainer.className = 'line-numbers';
    
    // 添加行号
    for (let i = 1; i <= lineCount; i++) {
        const lineNumber = document.createElement('div');
        lineNumber.textContent = i;
        lineNumbersContainer.appendChild(lineNumber);
    }
    
    // 将行号容器插入到pre元素中
    preElement.insertBefore(lineNumbersContainer, codeBlock);
    
    // 确保代码块有正确的类名
    if (!codeBlock.classList.contains('hljs')) {
        codeBlock.classList.add('hljs');
    }
}

function handleFileSelect(file) {
    if (!file) return;

    // 文件类型检查
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
    if (!file.type.startsWith('image/') || !allowedTypes.includes(file.type.toLowerCase())) {
        showLayuiAlert('请选择有效的图片文件（JPG、PNG、GIF、WebP）', 'error');
        return;
    }

    // 文件大小检查
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showLayuiAlert('图片大小不能超过10MB', 'error');
        return;
    }

    if (file.size === 0) {
        showLayuiAlert('文件为空，请选择有效的图片文件', 'error');
        return;
    }

    // 显示文件信息
    document.getElementById('file-name').textContent = file.name;
    document.getElementById('file-size').textContent = formatFileSize(file.size);
    document.getElementById('file-info').classList.remove('hidden');
    
    // 检查账号选择
    const accountSelect = document.getElementById('upload-account');
    if (accountSelect && accountSelect.value) {
        document.getElementById('upload-button').disabled = false;
    }
}

// 重置文件选择
function resetFileSelection() {
    document.getElementById('file-info').classList.add('hidden');
    document.getElementById('upload-button').disabled = true;
    document.getElementById('image-file').value = '';
    document.getElementById('upload-area').classList.remove('border-blue-400', 'bg-blue-50');
}

// 处理文件选择
function handleFileSelect(file) {
    if (!file) return;

    // 文件类型检查
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
    if (!file.type.startsWith('image/') || !allowedTypes.includes(file.type.toLowerCase())) {
        showNotification('请选择有效的图片文件（JPG、PNG、GIF、WebP）', 'error');
        return;
    }

    // 文件大小检查
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
        showNotification('图片大小不能超过10MB', 'error');
        return;
    }

    if (file.size === 0) {
        showNotification('文件为空，请选择有效的图片文件', 'error');
        return;
    }

    // 显示文件信息
    document.getElementById('file-name').textContent = file.name;
    document.getElementById('file-size').textContent = formatFileSize(file.size);
    document.getElementById('file-info').classList.remove('hidden');
    
    // 检查账号选择
    const accountSelect = document.getElementById('upload-account');
    if (accountSelect && accountSelect.value) {
        document.getElementById('upload-button').disabled = false;
    }
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 更新图片列表显示
function updateImagesList(images) {
    const container = document.getElementById('images-list');
    const emptyMessage = document.getElementById('empty-images');
    const imagesCount = document.getElementById('images-count');
    
    if (!container) return;
    
    imagesCount.textContent = images ? images.length : 0;
    
    if (!images || images.length === 0) {
        container.classList.add('hidden');
        emptyMessage.classList.remove('hidden');
        return;
    }
    
    container.classList.remove('hidden');
    emptyMessage.classList.add('hidden');
    
    container.innerHTML = images.map((image, index) => `
        <div class="group relative bg-white rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition-all duration-200">
            <div class="aspect-square bg-gray-100 overflow-hidden">
                <img src="${image.url}" 
                     alt="${image.name || '图片'}" 
                     class="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105 cursor-pointer"
                     onclick="previewImage('${image.url}')"
                     loading="lazy"
                     onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjZjNmNGY2Ii8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvbnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNCIgZmlsbD0iIzljYTNkYiIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPuWbvueJh+WKoOi9veWksei0pTwvdGV4dD48L3N2Zz4='" referrerpolicy="no-referrer">
            </div>
            
            <div class="p-3">
                <p class="text-sm font-medium text-gray-800 truncate" title="${image.name || '未命名'}">
                    ${image.name || '未命名'}
                </p>
                <p class="text-xs text-gray-500 mt-1 truncate">
                    ${image.upload_account || '未知用户'}
                </p>
                <p class="text-xs text-gray-400 mt-1">
                    ${image.upload_time || ''}
                </p>
            </div>
            
            <!-- 悬停操作按钮 -->
            <div class="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-20 transition-all duration-200 flex items-center justify-center opacity-0 group-hover:opacity-100">
                <div class="flex space-x-2">
                    <button onclick="copyImageUrl('${image.url}')" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="复制URL">
                        <i class="fa fa-copy text-gray-700 text-sm"></i>
                    </button>
                    <button onclick="previewImage('${image.url}')" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="预览">
                        <i class="fa fa-eye text-blue-600 text-sm"></i>
                    </button>
                    <button onclick="deleteImage('${image.url}')" 
                            class="p-2 bg-white rounded-full shadow-lg hover:bg-gray-50 transition transform hover:scale-110"
                            title="删除">
                        <i class="fa fa-trash text-red-600 text-sm"></i>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

// 图片预览功能
function previewImage(image) {
    currentPreviewUrl = image.url;
    document.getElementById('preview-image').src = image;
    document.getElementById('preview-title').textContent = image.name || '图片预览';
    document.getElementById('image-preview-modal').classList.remove('hidden');
}

function deleteImage(url) {
    layui.use('layer', function(){
        const layer = layui.layer;
        
        layer.confirm('确定要删除这张图片吗？此操作不可恢复！', {
            icon: 3,
            title: '确认删除'
        }, function(index){
            fetch('/api/delete_image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_url: url })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showLayuiAlert('图片删除成功', 'success');
                    loadImages();
                    closePreviewModal();
                } else {
                    showLayuiAlert(data.message || '删除失败', 'error');
                }
            })
            .catch(error => {
                console.error('删除图片失败:', error);
                showLayuiAlert('删除图片失败，请检查网络连接', 'error');
            });
            
            layer.close(index);
        });
    });
}

function previewImage(image) {
    currentPreviewUrl = image.url;
    document.getElementById('preview-image').src = image;
    document.getElementById('preview-title').textContent = image.name || '图片预览';
    document.getElementById('image-preview-modal').classList.remove('hidden');
}

function closePreviewModal() {
    document.getElementById('image-preview-modal').classList.add('hidden');
    currentPreviewUrl = '';
}

// 回退复制方法
function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    
    // 避免滚动到底部
    textArea.style.top = '0';
    textArea.style.left = '0';
    textArea.style.position = 'fixed';
    
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            showNotification('日志内容已复制到剪贴板', 'success');
        } else {
            showNotification('复制失败，请手动复制', 'error');
        }
    } catch (err) {
        console.error('回退复制也失败:', err);
        showNotification('复制失败，请手动复制', 'error');
    }
    
    document.body.removeChild(textArea);
}

// 滚动到日志顶部
function scrollLogsToTop() {
    const logContainer = document.getElementById('log-container');
    if (logContainer) {
        logContainer.scrollTop = 0;
    }
}

// 滚动到日志底部
function scrollLogsToBottom() {
    const logContainer = document.getElementById('log-container');
    if (logContainer) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}

// 切换自动滚动
function toggleAutoScroll() {
    autoScrollEnabled = !autoScrollEnabled;
    const btn = document.getElementById('auto-scroll-btn');
    
    if (btn) {
        if (autoScrollEnabled) {
            btn.classList.remove('bg-gray-600');
            btn.classList.add('bg-green-600');
            btn.innerHTML = '<i class="fa fa-magic mr-1"></i>自动滚动';
            showNotification('已启用自动滚动', 'success');
        } else {
            btn.classList.remove('bg-green-600');
            btn.classList.add('bg-gray-600');
            btn.innerHTML = '<i class="fa fa-pause mr-1"></i>暂停滚动';
            showNotification('已暂停自动滚动', 'warning');
        }
    }
}

// 获取日志
function fetchLogs() {
    fetch('/api/get_logs?limit=500')
        .then(response => response.json())
        .then(data => {
            if (data.logs && data.logs.length > 0) {
                currentLogs = data.logs;
                renderLogs();
            } else {
                const logContainer = document.getElementById('log-container');
                if (logContainer) {
                    logContainer.innerHTML = '<div class="text-center text-gray-500 py-8">暂无日志</div>';
                }
                updateLogStats(0, 0);
            }
        })
        .catch(error => {
            console.error('获取日志失败:', error);
            const logContainer = document.getElementById('log-container');
            if (logContainer) {
                logContainer.innerHTML = '<div class="text-center text-red-500 py-8">获取日志失败</div>';
            }
        });
}

// 清除所有日志
function clearAllLogs() {
    layer.confirm('确定要清空所有日志吗？此操作不可恢复！', {
            icon: 3,
            title: '确认删除'
        }, function(index) {
            fetch('/api/clear_logs', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    showNotification(data.message, data.success ? 'success' : 'error');
                    if (data.success) {
                        // 清空当前日志显示
                        currentLogs = [];
                        renderLogs();
                    }
                })
                .catch(error => {
                    console.error('清除日志失败:', error);
                    showNotification('清除日志失败，请检查网络连接', 'error');
                });
            layer.close(index);
        })
}

// GitHub讨论区功能
let currentDiscussions = [];
let currentDiscussion = null;

// 显示GitHub配置模态框
function showGitHubConfigModal() {
    fetch('/api/github/config')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const form = document.getElementById('github-config-form');
                const config = data.config;
                
                form.client_id.value = config.client_id || '';
                form.client_secret.value = '';
                form.repo_owner.value = config.repo_owner || '7Hello80';
                form.repo_name.value = config.repo_name || 'Bilibili_PrivateMessage_Bot';
                
                document.getElementById('github-config-modal').classList.remove('hidden');
            }
        })
        .catch(error => {
            console.error('获取GitHub配置失败:', error);
            showNotification('获取配置失败', 'error');
        });
}

function hideGitHubConfigModal() {
    document.getElementById('github-config-modal').classList.add('hidden');
}

// GitHub登录
function githubLogin() {
    window.location.href = '/github/login';
}

// GitHub退出登录
function githubLogout() {
    layer.confirm('确定要退出GitHub登录吗？', {
        icon: 3,
        title: '确认退出'
    }, function(index) {
        window.location.href = '/github/logout';
        layer.close(index);
    });
}

// 加载讨论列表
function loadDiscussions() {
    const container = document.getElementById('discussions-list');
    if (!container) return;
    
    container.innerHTML = `
        <div class="text-center text-gray-500 py-8">
            <i class="fa fa-spinner fa-spin text-2xl mb-2"></i>
            <p>加载讨论列表中...</p>
        </div>
    `;
    
    fetch('/api/github/discussions?limit=20')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentDiscussions = data.discussions || [];
                updateDiscussionsList();
                checkGitHubAuth();
            } else {
                container.innerHTML = `
                    <div class="text-center text-red-500 py-8">
                        <i class="fa fa-exclamation-triangle text-2xl mb-2"></i>
                        <p>${data.message || '加载讨论列表失败'}</p>
                    </div>
                `;
                checkGitHubAuth();
            }
        })
        .catch(error => {
            console.error('加载讨论列表失败:', error);
            container.innerHTML = `
                <div class="text-center text-red-500 py-8">
                    <i class="fa fa-exclamation-triangle text-2xl mb-2"></i>
                    <p>加载讨论列表失败，请检查网络连接</p>
                </div>
            `;
            checkGitHubAuth();
        });
}

function deleteComment(discussionNumber, commentId, commentAuthor) {
    // 获取当前GitHub用户信息
    fetch('/api/github/user')
        .then(response => response.json())
        .then(userData => {
            if (!userData.success) {
                showNotification('无法获取用户信息', 'error');
                return;
            }
            
            const currentUser = userData.user.login;
            
            // 验证评论是否属于当前用户
            if (commentAuthor !== currentUser) {
                showNotification('只能删除自己的评论', 'error');
                return;
            }
            
            // 确认删除
            layer.confirm('确定要删除这条评论吗？此操作不可撤销！', {
                icon: 3,
                title: '确认删除'
            }, function(index) {
                // 发送删除请求
                fetch(`/api/github/discussions/${discussionNumber}/comments/${commentId}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' }
                })
                .then(response => response.json())
                .then(data => {
                    showNotification(data.message, data.success ? 'success' : 'error');
                    if (data.success) {
                        // 重新加载讨论详情
                        showDiscussionDetail(discussionNumber);
                    }
                })
                .catch(error => {
                    console.error('删除评论失败:', error);
                    showNotification('删除评论失败', 'error');
                });
                
                layer.close(index);
            });
        })
        .catch(error => {
            console.error('获取用户信息失败:', error);
            showNotification('获取用户信息失败', 'error');
        });
}

// 更新讨论列表显示
function updateDiscussionsList() {
    const container = document.getElementById('discussions-list');
    if (!container) return;
    
    if (!currentDiscussions || currentDiscussions.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <i class="fa fa-comments text-3xl mb-3"></i>
                <p>暂无讨论</p>
                <p class="text-sm mt-2">点击"新建讨论"创建第一个讨论</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = currentDiscussions.map(discussion => `
        <div class="border border-gray-200 rounded-lg p-4 mb-4 bg-white hover:bg-gray-50 transition cursor-pointer" 
             onclick="showDiscussionDetail(${discussion.number})">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center space-x-3">
                    <img src="${discussion.user.avatar_url}" alt="${discussion.user.login}" class="w-8 h-8 rounded-full">
                    <div>
                        <h4 class="text-lg font-medium text-gray-800">${discussion.title}</h4>
                        <p class="text-sm text-gray-600">
                            由 <span class="font-medium">${discussion.user.login}</span> 创建于 ${formatDate(discussion.created_at)}
                        </p>
                    </div>
                </div>
                <div class="flex items-center space-x-2">
                    <span class="px-2 py-1 text-xs rounded-full ${discussion.state === 'open' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                        ${discussion.state === 'open' ? '开放' : '已关闭'}
                    </span>
                    <span class="flex items-center text-sm text-gray-500">
                        <i class="fa fa-comment mr-1"></i> ${discussion.comments_count}
                    </span>
                </div>
            </div>
            
            <div class="text-gray-600 line-clamp-2 markdown-body">
                ${marked.parse(discussion.body || '无内容')}
            </div>
            
            ${discussion.labels && discussion.labels.length > 0 ? `
            <div class="mt-3 flex flex-wrap gap-1">
                ${discussion.labels.map(label => `
                    <span class="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">${label}</span>
                `).join('')}
            </div>
            ` : ''}
        </div>
    `).join('');
    initCodeHighlighting();
}

// 显示讨论详情
function showDiscussionDetail(discussionNumber) {
    fetch(`/api/github/discussions/${discussionNumber}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentDiscussion = data.discussion;
                updateDiscussionDetailModal();
                document.getElementById('discussion-detail-modal').classList.remove('hidden');
            } else {
                showNotification(data.message || '获取讨论详情失败', 'error');
            }
        })
        .catch(error => {
            console.error('获取讨论详情失败:', error);
            showNotification('获取讨论详情失败', 'error');
        });
}

function updateDiscussionDetailModal() {
    if (!currentDiscussion) return;
    
    document.getElementById('discussion-title').textContent = currentDiscussion.title || '无标题';
    document.getElementById('current-discussion-number').value = currentDiscussion.number;
    
    const content = marked.parse((currentDiscussion.body || '无内容'));
    
    document.getElementById('discussion-content').innerHTML = `
        <div class="flex items-center space-x-3 mb-4">
            <img src="${currentDiscussion.user.avatar_url}" alt="${currentDiscussion.user.login}" class="w-10 h-10 rounded-full">
            <div>
                <p class="font-medium text-gray-800">${currentDiscussion.user.login}</p>
                <p class="text-sm text-gray-600">${formatDate(currentDiscussion.created_at)}</p>
            </div>
        </div>
        <div class="prose max-w-none markdown-body">
            ${content}
        </div>
    `;
    
    // 更新评论列表
    const commentsContainer = document.getElementById('comments-list');
    if (currentDiscussion.comments && currentDiscussion.comments.length > 0) {
        commentsContainer.innerHTML = currentDiscussion.comments.map(comment => {
            const commentBody = marked.parse(comment.body || '');
            
            // 获取当前用户信息以决定是否显示删除按钮
            let deleteButton = '';
            fetch('/api/github/user')
                .then(response => response.json())
                .then(userData => {
                    if (userData.success && userData.user.login === comment.user.login) {
                        const deleteBtn = document.getElementById(`delete-comment-${comment.id}`);
                        if (deleteBtn) {
                            deleteBtn.style.display = 'block';
                        }
                    }
                })
                .catch(console.error);
            
            return `
            <div class="border border-gray-200 rounded-lg p-4 bg-white relative">
                <div class="flex items-center space-x-3 mb-3">
                    <img src="${comment.user.avatar_url}" alt="${comment.user.login}" class="w-8 h-8 rounded-full">
                    <div class="flex-1">
                        <p class="font-medium text-gray-800">${comment.user.login}</p>
                        <p class="text-sm text-gray-600">${formatDate(comment.created_at)}</p>
                    </div>
                    <button 
                        data-comment-id="${comment.id}"
                        onclick="deleteComment(${currentDiscussion.number}, ${comment.id}, '${comment.user.login}')"
                        class="delete-comment-btn opacity-0 group-hover:opacity-100 transition-all duration-300 transform translate-x-2 group-hover:translate-x-0 
                               bg-gradient-to-r from-red-500 to-pink-500 hover:from-red-600 hover:to-pink-600 
                               text-white px-4 py-2 rounded-lg shadow-lg hover:shadow-xl 
                               flex items-center space-x-2 text-sm font-medium
                               hover:scale-105 active:scale-95 transition-all duration-200"
                        title="删除评论"
                        style="display: none;"
                    >
                        <i class="fa fa-trash-alt text-xs"></i>
                        <span>删除</span>
                    </button>
                </div>
                <div class="text-gray-700 whitespace-pre-wrap markdown-body">${commentBody}</div>
            </div>
            `;
        }).join('');
    } else {
        commentsContainer.innerHTML = '<p class="text-gray-500 text-center py-4">暂无评论</p>';
    }
    
    // 延迟检查并显示删除按钮
    setTimeout(() => {
        checkAndShowDeleteButtons();
    }, 500);
    
    initCodeHighlighting();
}

function checkAndShowDeleteButtons() {
    fetch('/api/github/user')
        .then(response => response.json())
        .then(userData => {
            if (userData.success) {
                const currentUser = userData.user.login;
                
                // 遍历所有评论，显示当前用户的删除按钮
                document.querySelectorAll('.delete-comment-btn').forEach(button => {
                    const commentId = button.getAttribute('data-comment-id');
                    const comment = currentDiscussion.comments.find(c => c.id == commentId);
                    if (comment && comment.user.login === currentUser) {
                        button.style.display = 'flex';
                        setTimeout(() => {
                            button.style.opacity = '1';
                            button.style.transform = 'translateX(0)';
                        }, 100);
                    }
                });
            }
        })
        .catch(error => {
            console.error('检查删除按钮失败:', error);
        });
}

function hideDiscussionDetailModal() {
    document.getElementById('discussion-detail-modal').classList.add('hidden');
    currentDiscussion = null;
}

// 显示创建讨论模态框
function showCreateDiscussionModal() {
    document.getElementById('create-discussion-modal').classList.remove('hidden');
}

function hideCreateDiscussionModal() {
    document.getElementById('create-discussion-modal').classList.add('hidden');
    document.getElementById('create-discussion-form').reset();
}

// 检查GitHub认证状态
function checkGitHubAuth() {
    fetch('/api/github/config')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const config = data.config;
                const loginBtn = document.getElementById('github-login-btn');
                const logoutBtn = document.getElementById('github-logout-btn');
                const userInfo = document.getElementById('github-user-info');
                
                if (config.is_authenticated) {
                    loginBtn.classList.add('hidden');
                    logoutBtn.classList.remove('hidden');
                    
                    // 获取用户信息
                    fetch('/api/github/user')
                        .then(response => response.json())
                        .then(userData => {
                            if (userData.success) {
                                userInfo.classList.remove('hidden');
                                document.getElementById('github-avatar').src = userData.user.avatar_url;
                                document.getElementById('github-username').textContent = userData.user.login;
                                document.getElementById('github-display-name').textContent = userData.user.name || '';
                            }
                        });
                } else {
                    loginBtn.classList.remove('hidden');
                    logoutBtn.classList.add('hidden');
                    userInfo.classList.add('hidden');
                }
            }
        })
        .catch(error => {
            console.error('检查GitHub认证状态失败:', error);
        });
}

// 初始化GitHub相关事件监听
document.addEventListener('DOMContentLoaded', function() {
    // GitHub配置表单提交
    const githubConfigForm = document.getElementById('github-config-form');
    if (githubConfigForm) {
        githubConfigForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            const configData = {
                client_id: formData.get('client_id'),
                client_secret: formData.get('client_secret'),
                repo_owner: formData.get('repo_owner'),
                repo_name: formData.get('repo_name')
            };
            
            fetch('/api/github/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(configData)
            })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    hideGitHubConfigModal();
                    checkGitHubAuth();
                }
            })
            .catch(error => {
                console.error('更新GitHub配置失败:', error);
                showNotification('更新配置失败', 'error');
            });
        });
    }
    
    // 创建讨论表单提交
    const createDiscussionForm = document.getElementById('create-discussion-form');
    if (createDiscussionForm) {
        createDiscussionForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            const discussionData = {
                title: formData.get('title'),
                body: formData.get('body'),
                labels: formData.get('labels') ? formData.get('labels').split(',').map(label => label.trim()) : []
            };
            
            fetch('/api/github/discussions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(discussionData)
            })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    hideCreateDiscussionModal();
                    loadDiscussions();
                }
            })
            .catch(error => {
                console.error('创建讨论失败:', error);
                showNotification('创建讨论失败', 'error');
            });
        });
    }
    
    // 创建评论表单提交
    const createCommentForm = document.getElementById('create-comment-form');
    if (createCommentForm) {
        createCommentForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const discussionNumber = document.getElementById('current-discussion-number').value;
            
            const commentData = {
                body: formData.get('body')
            };
            
            fetch(`/api/github/discussions/${discussionNumber}/comments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(commentData)
            })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    createCommentForm.reset();
                    // 重新加载讨论详情
                    showDiscussionDetail(discussionNumber);
                }
            })
            .catch(error => {
                console.error('发布评论失败:', error);
                showNotification('发布评论失败', 'error');
            });
        });
    }
});

// 在初始化部分添加GitHub讨论区初始化
function initGitHubDiscussions() {
    checkGitHubAuth();
    loadDiscussions();
}

document.addEventListener('DOMContentLoaded', function() {
    // 编辑账号模态框
    const editAutoReplyFollowCheckbox = document.getElementById('edit-account-auto-reply-follow');
    const editFollowReplyContainer = document.getElementById('follow-reply-container');
    
    if (editAutoReplyFollowCheckbox && editFollowReplyContainer) {
        editAutoReplyFollowCheckbox.addEventListener('change', function() {
            if (this.checked) {
                editFollowReplyContainer.classList.remove('hidden');
            } else {
                editFollowReplyContainer.classList.add('hidden');
            }
        });
    }

    // 修改关键词表单提交
    const editKeywordForm = document.getElementById('edit-keyword-form');
    if (editKeywordForm) {
        editKeywordForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            saveKeywordEdit(formData);
        });
    }

    // 添加账号模态框
    const addAutoReplyFollowCheckbox = document.getElementById('add-account-auto-reply-follow');
    const addFollowReplyContainer = document.getElementById('add-follow-reply-container');
    
    if (addAutoReplyFollowCheckbox && addFollowReplyContainer) {
        addAutoReplyFollowCheckbox.addEventListener('change', function() {
            if (this.checked) {
                addFollowReplyContainer.classList.remove('hidden');
            } else {
                addFollowReplyContainer.classList.add('hidden');
            }
        });
    }
});

// 多账号管理功能
function showAddAccountModal() {
    // 生成随机的DEVICE_ID
    const deviceId = generateDeviceId();
    document.querySelector('input[name="device_id"]').value = deviceId;
    
    // 重置扫码登录区域
    document.getElementById('qrcode-container').classList.add('hidden');
    document.getElementById('start-qrcode-login').classList.remove('hidden');
    
    document.getElementById('add-account-modal').classList.remove('hidden');

    document.getElementById('add-account-auto-reply-follow').checked = false;
    document.getElementById('add-account-follow-reply-message').value = '感谢关注！';
    document.getElementById('add-follow-reply-container').classList.add('hidden');
}

function hideAddAccountModal() {
    document.getElementById('add-account-modal').classList.add('hidden');
    
    // 停止扫码轮询
    if (window.qrcodePolling) {
        clearInterval(window.qrcodePolling);
        window.qrcodePolling = null;
    }
}

function generateDeviceId() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    }).toUpperCase();
}

// 扫码登录功能
function startQrcodeLogin() {
    const qrcodeContainer = document.getElementById('qrcode-container');
    const startButton = document.getElementById('start-qrcode-login');
    
    // 显示加载状态
    qrcodeContainer.classList.remove('hidden');
    startButton.classList.add('hidden');
    
    document.getElementById('qrcode-status').textContent = '正在获取二维码...';
    document.getElementById('qrcode-img').src = '';
    
    // 获取二维码
    fetch('/api/bilibili_qrcode')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // 显示二维码
                document.getElementById('qrcode-img').src = data.data.qrcode_img;
                document.getElementById('qrcode-status').textContent = '请使用哔哩哔哩APP扫码登录';
                
                // 开始轮询扫码状态
                startQrcodePolling(data.data.qrcode_key);
            } else {
                document.getElementById('qrcode-status').textContent = '获取二维码失败: ' + data.message;
                startButton.classList.remove('hidden');
            }
        })
        .catch(error => {
            console.error('获取二维码失败:', error);
            document.getElementById('qrcode-status').textContent = '获取二维码失败，请检查网络连接';
            startButton.classList.remove('hidden');
        });
}

function startQrcodePolling(qrcodeKey) {
    // 停止之前的轮询
    if (window.qrcodePolling) {
        clearInterval(window.qrcodePolling);
    }
    
    // 开始新的轮询
    window.qrcodePolling = setInterval(() => {
        fetch(`/api/bilibili_qrcode_status?qrcode_key=${encodeURIComponent(qrcodeKey)}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // 登录成功
                    clearInterval(window.qrcodePolling);
                    window.qrcodePolling = null;
                    
                    // 自动填充表单
                    document.querySelector('input[name="sessdata"]').value = data.data.sessdata || '';
                    document.querySelector('input[name="bili_jct"]').value = data.data.bili_jct || '';
                    document.querySelector('input[name="self_uid"]').value = data.data.mid || '';
                    
                    document.getElementById('qrcode-status').innerHTML = 
                        `<span class="text-green-600">登录成功！用户信息已自动填充</span>`;
                    
                    showNotification('扫码登录成功，用户信息已自动填充', 'success');
                } else {
                    // 根据状态码更新提示信息
                    const statusElement = document.getElementById('qrcode-status');
                    switch(data.code) {
                        case 86101:
                            statusElement.textContent = '等待扫码...';
                            break;
                        case 86090:
                            statusElement.innerHTML = '<span class="text-yellow-600">已扫码，请在手机上确认登录</span>';
                            break;
                        case 86038:
                            statusElement.innerHTML = '<span class="text-red-600">二维码已过期，请重新扫码</span>';
                            clearInterval(window.qrcodePolling);
                            window.qrcodePolling = null;
                            document.getElementById('start-qrcode-login').classList.remove('hidden');
                            break;
                        default:
                            statusElement.textContent = data.message || '未知状态';
                    }
                }
            })
            .catch(error => {
                console.error('检查扫码状态失败:', error);
                document.getElementById('qrcode-status').textContent = '检查状态失败，请重试';
            });
    }, 2000); // 每2秒检查一次
}

function cancelQrcodeLogin() {
    // 停止轮询
    if (window.qrcodePolling) {
        clearInterval(window.qrcodePolling);
        window.qrcodePolling = null;
    }
    
    // 隐藏二维码容器
    document.getElementById('qrcode-container').classList.add('hidden');
    document.getElementById('start-qrcode-login').classList.remove('hidden');
}

// 为扫码登录按钮添加事件监听
document.addEventListener('DOMContentLoaded', function() {
    const startButton = document.getElementById('start-qrcode-login');
    const cancelButton = document.getElementById('cancel-qrcode-login');
    
    if (startButton) {
        startButton.addEventListener('click', startQrcodeLogin);
    }
    
    if (cancelButton) {
        cancelButton.addEventListener('click', cancelQrcodeLogin);
    }
});

function loadAccounts() {
    fetch('/api/get_accounts')
        .then(response => response.json())
        .then(data => {
            updateAccountsList(data.accounts);
            updateGlobalKeywordsList(data.global_keywords);
        })
        .catch(error => {
            console.error('获取账号列表失败:', error);
        });
}

function updateAccountsList(accounts) {
    const container = document.getElementById('accounts-list');
    if (!container) return;
    
    if (!accounts || accounts.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <i class="fa fa-users text-3xl mb-3"></i>
                <p>暂无账号</p>
                <p class="text-sm mt-2">点击右上角"添加账号"按钮来添加第一个账号</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = accounts.map((account, index) => `
        <div class="border border-gray-200 rounded-lg p-4 mb-4 bg-white hover:bg-gray-50 transition">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center space-x-3">
                    <div class="w-3 h-3 rounded-full ${account.enabled ? 'bg-green-500' : 'bg-gray-400'}"></div>
                    <h4 class="text-lg font-medium text-gray-800">${account.name}</h4>
                    <span class="text-sm px-2 py-1 bg-blue-100 text-blue-800 rounded">UID: ${account.config.self_uid}</span>
                </div>
                <div class="flex items-center space-x-2">
                    <button onclick="toggleAccount(${index})" 
                            class="px-3 py-1 text-sm ${account.enabled ? 'bg-yellow-600 hover:bg-yellow-700' : 'bg-green-600 hover:bg-green-700'} text-white rounded transition">
                        ${account.enabled ? '禁用' : '启用'}
                    </button>
                    <button onclick="editAccount(${index})" 
                            class="px-3 py-1 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded transition">
                        编辑
                    </button>
                    <button onclick="deleteAccount(${index})" 
                            class="px-3 py-1 text-sm bg-red-600 hover:bg-red-700 text-white rounded transition">
                        删除
                    </button>
                </div>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                    <span class="text-gray-600">艾特用户:</span>
                    <span class="ml-2 font-medium ${account.at_user ? 'text-green-600' : 'text-red-600'}">
                        ${account.at_user ? '开启' : '关闭'}
                    </span>
                </div>
                <div>
                    <span class="text-gray-600">自动关注:</span>
                    <span class="ml-2 font-medium ${account.auto_focus ? 'text-green-600' : 'text-red-600'}">
                        ${account.auto_focus ? '开启' : '关闭'}
                    </span>
                </div>
                <div>
                    <span class="text-gray-600">关键词数量:</span>
                    <span class="ml-2 font-medium">${Object.keys(account.keyword || {}).length}</span>
                </div>
            </div>
            
            ${Object.keys(account.keyword || {}).length > 0 ? `
            <div class="mt-3 pt-3 border-t border-gray-200">
                <h5 class="text-sm font-medium text-gray-700 mb-2">账号关键词:</h5>
                <div class="space-y-1">
                    ${Object.entries(account.keyword).map(([keyword, reply]) => `
                        <div class="flex items-center justify-between p-3 border border-gray-200 rounded-lg bg-white">
                            <div class="flex-1">
                                <div class="font-medium text-gray-800">${keyword}</div>
                                <div class="text-sm text-gray-600">${reply}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            ` : ''}
        </div>
    `).join('');
}

function updateGlobalKeywordsList(keywords) {
    const container = document.getElementById('global-keywords-list');
    if (!container) return;
    
    if (!keywords || Object.keys(keywords).length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无全局关键词</div>';
        return;
    }
    
    container.innerHTML = Object.entries(keywords).map(([keyword, reply]) => `
        <div class="flex items-center justify-between p-3 border border-gray-200 rounded-lg mb-2">
            <div class="flex-1">
                <div class="font-medium text-gray-800">${keyword}</div>
                <div class="text-sm text-gray-600">${reply}</div>
            </div>
            <button onclick="deleteGlobalKeyword('${keyword}')" 
                    class="ml-4 px-3 py-1 bg-red-600 text-white rounded text-sm hover:bg-red-700 transition">
                <i class="fa fa-trash"></i>
            </button>
        </div>
    `).join('');
}

function get_announcement() {
    fetch('/api/get_announcement')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('announcement-text').innerHTML = data.message;
            } else {
                showNotification('获取公告失败', 'error');
                document.getElementById('announcement-text').innerHTML = '获取公告失败';
            }
        })
        .catch(error => {
            console.error('获取公告失败:', error);
            showNotification('操作失败，请检查网络连接', 'error');
            document.getElementById('announcement-text').innerHTML = '获取公告失败';
        });
}

function toggleAccount(index) {
    fetch(`/api/toggle_account/${index}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                loadAccounts();
                fetchBotStatus(); // 更新状态显示
            }
        })
        .catch(error => {
            console.error('切换账号状态失败:', error);
            showNotification('操作失败，请检查网络连接', 'error');
        });
}

let currentEditingAccountIndex = -1;

function editAccount(index) {
    currentEditingAccountIndex = index;
    
    fetch('/api/get_accounts')
        .then(response => response.json())
        .then(data => {
            const account = data.accounts[index];
            if (account) {
                // 填充表单数据
                document.getElementById('edit-account-index').value = index;
                document.getElementById('edit-account-name').value = account.name || '';
                document.getElementById('edit-account-sessdata').value = account.config.sessdata || '';
                document.getElementById('edit-account-bili_jct').value = account.config.bili_jct || '';
                document.getElementById('edit-account-self_uid').value = account.config.self_uid || '';
                document.getElementById('edit-account-device_id').value = account.config.device_id || '';
                document.getElementById('edit-account-enabled').checked = account.enabled || false;
                document.getElementById('edit-account-at-user').checked = account.at_user || false;
                document.getElementById('edit-account-auto-focus').checked = account.auto_focus || false;
                document.getElementById('edit-account-no-focus').checked = account.no_focus_hf || false;
                
                // 更新关键词列表
                updateAccountKeywordsList(account.keyword || {});

                document.getElementById('edit-account-auto-reply-follow').checked = account.auto_reply_follow || false;
                document.getElementById('edit-account-follow-reply-message').value = account.follow_reply_message || '感谢关注！';
                
                // 根据开关状态显示/隐藏消息输入框
                const followReplyContainer = document.getElementById('follow-reply-container');
                if (account.auto_reply_follow) {
                    followReplyContainer.classList.remove('hidden');
                } else {
                    followReplyContainer.classList.add('hidden');
                }
                
                // 显示模态框
                document.getElementById('edit-account-modal').classList.remove('hidden');
            }
        })
        .catch(error => {
            console.error('获取账号详情失败:', error);
            showNotification('获取账号详情失败', 'error');
        });
}

function hideEditAccountModal() {
    document.getElementById('edit-account-modal').classList.add('hidden');
    currentEditingAccountIndex = -1;
}

function updateAccountKeywordsList(keywords) {
    const container = document.getElementById('edit-account-keywords-list');
    if (!container) return;
    
    if (!keywords || Object.keys(keywords).length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无关键词</div>';
        return;
    }
    
    container.innerHTML = Object.entries(keywords).map(([keyword, reply]) => {
        // 使用数据属性存储原始数据，避免转义问题
        return `
        <div class="keyword-item flex items-start justify-between p-3 border border-gray-200 rounded-lg bg-white mb-2" 
             data-keyword="${encodeURIComponent(keyword)}" 
             data-reply="${encodeURIComponent(reply)}">
            <div class="flex-1">
                <div class="font-medium text-gray-800 mb-2">${keyword}</div>
                <div class="text-sm text-gray-600 whitespace-pre-wrap bg-gray-50 p-2 rounded border">${reply}</div>
            </div>
            <div class="flex space-x-2 ml-4 self-start">
                <button type="button" class="edit-keyword-btn px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 transition">
                    <i class="fa fa-edit"></i>
                </button>
                <button type="button" class="delete-keyword-btn px-3 py-1 bg-red-600 text-white rounded text-sm hover:bg-red-700 transition">
                    <i class="fa fa-trash"></i>
                </button>
            </div>
        </div>
        `;
    }).join('');
    
    // 为按钮添加事件监听（使用事件委托）
    container.addEventListener('click', function(e) {
        const keywordItem = e.target.closest('.keyword-item');
        if (!keywordItem) return;
        
        if (e.target.closest('.edit-keyword-btn')) {
            const keyword = decodeURIComponent(keywordItem.getAttribute('data-keyword'));
            const reply = decodeURIComponent(keywordItem.getAttribute('data-reply'));
            openEditKeywordModal(keyword, reply);
        } else if (e.target.closest('.delete-keyword-btn')) {
            const keyword = decodeURIComponent(keywordItem.getAttribute('data-keyword'));
            deleteAccountKeyword(keyword);
        }
    });
}

function addAccountKeyword() {
    const keywordInput = document.getElementById('edit-account-keyword-input');
    const replyInput = document.getElementById('edit-account-reply-input');
    
    const keyword = keywordInput.value.trim();
    const reply = replyInput.value.trim();
    
    if (!keyword || !reply) {
        showNotification('关键词和回复内容不能为空', 'error');
        return;
    }
    
    if (currentEditingAccountIndex === -1) {
        showNotification('请先选择要编辑的账号', 'error');
        return;
    }
    
    fetch(`/api/add_account_keyword/${currentEditingAccountIndex}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword, reply })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success) {
            // 清空输入框
            keywordInput.value = '';
            replyInput.value = '';
            
            // 重新加载账号数据以更新关键词列表
            fetch('/api/get_accounts')
                .then(response => response.json())
                .then(data => {
                    const account = data.accounts[currentEditingAccountIndex];
                    if (account) {
                        updateAccountKeywordsList(account.keyword || {});
                    }
                });
        }
    })
    .catch(error => {
        console.error('添加关键词失败:', error);
        showNotification('添加关键词失败，请检查网络连接', 'error');
    });
}

function deleteAccountKeyword(keyword) {
    if (currentEditingAccountIndex === -1) {
        showNotification('请先选择要编辑的账号', 'error');
        return;
    }
    
    layer.confirm(`确定要删除关键词 "${keyword}" 吗？`, {
        icon: 3,
        title: '确认删除'
    }, function(index) {
        fetch(`/api/delete_account_keyword/${currentEditingAccountIndex}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                // 重新加载账号数据以更新关键词列表
                fetch('/api/get_accounts')
                    .then(response => response.json())
                    .then(data => {
                        const account = data.accounts[currentEditingAccountIndex];
                        if (account) {
                            updateAccountKeywordsList(account.keyword || {});
                        }
                    });
            }
        })
        .catch(error => {
            console.error('删除关键词失败:', error);
            showNotification('删除关键词失败，请检查网络连接', 'error');
        });
        layer.close(index);
    })
}

// 当前编辑的关键词
let currentEditingKeyword = null;

// 打开修改关键词模态框
function openEditKeywordModal(keyword, reply) {
    currentEditingKeyword = keyword;
    
    // 填充表单数据
    document.getElementById('edit-original-keyword').value = keyword;
    document.getElementById('edit-keyword-input').value = keyword;
    document.getElementById('edit-reply-input').value = reply;
    
    // 显示模态框
    document.getElementById('edit-keyword-modal').classList.remove('hidden');
}

// 隐藏修改关键词模态框
function hideEditKeywordModal() {
    document.getElementById('edit-keyword-modal').classList.add('hidden');
    currentEditingKeyword = null;
    document.getElementById('edit-keyword-form').reset();
}

// 保存关键词修改
function saveKeywordEdit(formData) {
    const originalKeyword = formData.get('original_keyword');
    const newKeyword = formData.get('keyword').trim();
    const newReply = formData.get('reply');
    
    if (!newKeyword || !newReply) {
        showNotification('关键词和回复内容不能为空', 'error');
        return;
    }
    
    if (currentEditingAccountIndex === -1) {
        showNotification('请先选择要编辑的账号', 'error');
        return;
    }
    
    // 先删除原关键词，再添加新关键词
    fetch(`/api/delete_account_keyword/${currentEditingAccountIndex}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: originalKeyword })
    })
    .then(response => response.json())
    .then(deleteData => {
        if (deleteData.success) {
            // 删除成功，添加新关键词
            return fetch(`/api/add_account_keyword/${currentEditingAccountIndex}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    keyword: newKeyword, 
                    reply: newReply 
                })
            });
        } else {
            throw new Error(deleteData.message || '删除原关键词失败');
        }
    })
    .then(response => response.json())
    .then(addData => {
        showNotification(addData.message, addData.success ? 'success' : 'error');
        if (addData.success) {
            hideEditKeywordModal();
            
            // 重新加载账号数据以更新关键词列表
            fetch('/api/get_accounts')
                .then(response => response.json())
                .then(data => {
                    const account = data.accounts[currentEditingAccountIndex];
                    if (account) {
                        updateAccountKeywordsList(account.keyword || {});
                    }
                });
        }
    })
    .catch(error => {
        console.error('修改关键词失败:', error);
        showNotification('修改关键词失败: ' + error.message, 'error');
    });
}

function deleteAccount(index) {
    layer.confirm('确定要删除这个账号吗？此操作不可恢复！', {
        icon: 3,
        title: '确认删除'
    }, function(index1) {
        fetch(`/api/delete_account/${index}`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    loadAccounts();
                    fetchBotStatus(); // 更新状态显示
                }
            })
            .catch(error => {
                console.error('删除账号失败:', error);
                showNotification('删除失败，请检查网络连接', 'error');
            });
        layer.close(index1);
    })
}

function deleteGlobalKeyword(keyword) {
    layer.confirm(`确定要删除全局关键词 "${keyword}" 吗？`, {
        icon: 3,
        title: '确认删除'
    }, function(index) {
        fetch('/api/get_accounts')
            .then(response => response.json())
            .then(data => {
                const globalKeywords = data.global_keywords || {};
                delete globalKeywords[keyword];
                
                return fetch('/api/update_global_keywords', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(globalKeywords)
                });
            })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success ? 'success' : 'error');
                if (data.success) {
                    loadAccounts();
                    fetchBotStatus(); // 更新状态显示
                }
            })
            .catch(error => {
                console.error('删除全局关键词失败:', error);
                showNotification('删除失败，请检查网络连接', 'error');
            });
        layer.close(index);
    })
}

function showGlobalKeywordModal() {
    document.getElementById('edit-account-modal-global').classList.remove('hidden');
}

function closeAddGlobalKeywordModal() {
    document.getElementById('edit-account-modal-global').classList.add('hidden');
}

function showAddGlobalKeywordModal() {
    const keyword = document.getElementById('edit-account-keyword-input-global').value.trim();
    if (keyword) {
        const reply = document.getElementById('edit-account-reply-input-global').value.trim();
        if (reply) {
            fetch('/api/get_accounts')
                .then(response => response.json())
                .then(data => {
                    const globalKeywords = data.global_keywords || {};
                    globalKeywords[keyword] = reply;
                    
                    return fetch('/api/update_global_keywords', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(globalKeywords)
                    });
                })
                .then(response => response.json())
                .then(data => {
                    showNotification(data.message, data.success ? 'success' : 'error');
                    if (data.success) {
                        loadAccounts();
                        fetchBotStatus(); // 更新状态显示
                    }
                    document.getElementById('edit-account-keyword-input-global').value = '';
                    document.getElementById('edit-account-reply-input-global').value = '';
                    closeAddGlobalKeywordModal();
                })
                .catch(error => {
                    console.error('添加全局关键词失败:', error);
                    showNotification('添加失败，请检查网络连接', 'error');
                    closeAddGlobalKeywordModal();
                });
        }
    }
}

function isVersionGreaterOrEqual(currentVersion, targetVersion) {
    const v1 = currentVersion.split('.').map(Number);
    const v2 = targetVersion.split('.').map(Number);
    
    const maxLength = Math.max(v1.length, v2.length);
    
    for (let i = 0; i < maxLength; i++) {
        const num1 = v1[i] || 0;
        const num2 = v2[i] || 0;
        
        if (num1 > num2) return true;
        if (num1 < num2) return false;
    }
    
    return true; // 版本相等
}

// 检查更新
function checkForUpdates() {
    fetch('/api/check_update')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.has_update && data.update_info) {
                const shouldUpdate = !isVersionGreaterOrEqual(
                    data.current_version || '0.0.0', 
                    data.update_info.version
                );
                
                if (shouldUpdate) {
                    showUpdateAlert(data.update_info, data.current_version);
                }
            }
        })
        .catch(error => {
            console.error('检查更新失败:', error);
        });
}

// 显示更新提示
function showUpdateAlert(updateInfo, currentVersion) {
    const alert = document.getElementById('update-alert');
    const currentVersionEl = document.getElementById('current-version');
    const latestVersionEl = document.getElementById('latest-version');
    const announcementEl = document.getElementById('update-announcement');
    const updateLink = document.getElementById('update-link');
    
    if (alert && currentVersionEl && latestVersionEl && announcementEl && updateLink) {
        currentVersionEl.textContent = `v${currentVersion}`;
        latestVersionEl.textContent = `v${updateInfo.version}`;
        announcementEl.innerHTML = updateInfo.announ || '有新功能和改进，请及时更新！';
        updateLink.href = updateInfo.url;
        
        alert.classList.remove('hidden');
    }
}

// 隐藏更新提示
function hideUpdateAlert() {
    const alert = document.getElementById('update-alert');
    if (alert) {
        alert.classList.add('hidden');
    }
}

// 手动检查更新
function manualCheckUpdate() {
    fetch('/api/check_update')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (data.has_update && data.update_info) {
                    const shouldUpdate = !isVersionGreaterOrEqual(
                        data.current_version || '0.0.0', 
                        data.update_info.version
                    );
                    
                    if (shouldUpdate) {
                        showUpdateAlert(data.update_info, data.current_version);
                        showNotification(`发现新版本 v${data.update_info.version}`, 'success');
                    } else {
                        showNotification('当前已是最新版本', 'info');
                    }
                } else {
                    showNotification('当前已是最新版本', 'info');
                }
            } else {
                showNotification(data.message || '检查更新失败', 'error');
            }
        })
        .catch(error => {
            console.error('检查更新失败:', error);
            showNotification('检查更新失败，请检查网络连接', 'error');
        });
}

// 添加账号表单提交
const addAccountForm = document.getElementById('add-account-form');
if (addAccountForm) {
    addAccountForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        
        const accountData = {
            name: formData.get('name'),
            sessdata: formData.get('sessdata'),
            bili_jct: formData.get('bili_jct'),
            self_uid: parseInt(formData.get('self_uid')),
            device_id: formData.get('device_id'),
            enabled: formData.get('enabled') === 'on',
            at_user: formData.get('at_user') === 'on',
            auto_focus: formData.get('auto_focus') === 'on',
            auto_reply_follow: formData.get('auto_reply_follow') === 'on',  // 新增
            no_focus_hf: formData.get("no_focus_hf") === 'on',
            follow_reply_message: formData.get('follow_reply_message') || '感谢关注！',  // 新增
            keywords: {}
        };
        
        fetch('/api/add_account', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(accountData)
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                hideAddAccountModal();
                this.reset();
                loadAccounts();
                fetchBotStatus(); // 更新状态显示
            }
        })
        .catch(error => {
            console.error('添加账号失败:', error);
            showNotification('添加失败，请检查网络连接', 'error');
        });
    });
}

// 编辑账号表单提交
const editAccountForm = document.getElementById('edit-account-form');
if (editAccountForm) {
    editAccountForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        const accountIndex = parseInt(formData.get('account_index'));
        
        const accountData = {
            name: formData.get('name'),
            sessdata: formData.get('sessdata'),
            bili_jct: formData.get('bili_jct'),
            self_uid: parseInt(formData.get('self_uid')),
            device_id: formData.get('device_id'),
            enabled: formData.get('enabled') === 'on',
            at_user: formData.get('at_user') === 'on',
            auto_focus: formData.get('auto_focus') === 'on',
            auto_reply_follow: formData.get('auto_reply_follow') === 'on',  // 新增
            no_focus_hf: formData.get('no_focus_hf') === 'on',
            follow_reply_message: formData.get('follow_reply_message') || '感谢关注！'  // 新增
        };
        
        fetch(`/api/update_account/${accountIndex}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(accountData)
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                hideEditAccountModal();
                loadAccounts();
                fetchBotStatus(); // 更新状态显示
            }
        })
        .catch(error => {
            console.error('更新账号失败:', error);
            showNotification('更新失败，请检查网络连接', 'error');
        });
    });
}

// 获取机器人状态
function fetchBotStatus() {
    fetch('/api/bot_status')
        .then(response => response.json())
        .then(data => {
            // 更新状态显示
            const statusText = document.getElementById('status-text');
            const startBtn = document.getElementById('start-btn');
            const stopBtn = document.getElementById('stop-btn');
            const restartBtn = document.getElementById('restart-btn');
            const totalAccountsCount = document.getElementById('total-accounts-count');
            const enabledAccountsCount = document.getElementById('enabled-accounts-count');
            const globalKeywordsCount = document.getElementById('global-keywords-count');
            const lastUpdate = document.getElementById('last-update');
            
            if (statusText) {
                if (data.running) {
                    statusText.innerHTML = '<span class="text-green-600 flex items-center"><i class="fa fa-circle animate-pulse mr-2"></i>运行中</span>';
                } else {
                    statusText.innerHTML = '<span class="text-red-600 flex items-center"><i class="fa fa-circle mr-2"></i>已停止</span>';
                }
            }
            
            if (startBtn) startBtn.disabled = data.running;
            if (stopBtn) stopBtn.disabled = !data.running;
            if (restartBtn) restartBtn.disabled = !data.running;
            
            // 更新账号数量
            if (totalAccountsCount) totalAccountsCount.textContent = data.total_accounts_count;
            if (enabledAccountsCount) enabledAccountsCount.textContent = data.enabled_accounts_count;
            
            // 更新全局关键词数量
            const globalKeywordsCountValue = Object.keys(data.global_keywords || {}).length;
            if (globalKeywordsCount) globalKeywordsCount.textContent = globalKeywordsCountValue;
            
            // 更新最后更新时间
            if (lastUpdate) lastUpdate.textContent = new Date().toLocaleString();
            
            // 如果是在账号管理页面，更新账号列表
            const accountsSection = document.getElementById('accounts');
            if (accountsSection && accountsSection.style.display !== 'none') {
                updateAccountsList(data.accounts);
                updateGlobalKeywordsList(data.global_keywords);
            }
        })
        .catch(error => {
            console.error('获取机器人状态失败:', error);
            const statusText = document.getElementById('status-text');
            if (statusText) {
                statusText.innerHTML = '<span class="text-red-600">获取状态失败</span>';
            }
        });
}

function updateProgressCircle(elementId, targetPercentage) {
    const circle = document.getElementById(elementId);
    if (!circle) return;
    
    // 获取当前进度（从stroke-dashoffset计算）
    const circumference = 283;
    const currentOffset = parseFloat(circle.style.strokeDashoffset || circumference);
    const currentPercentage = 100 - (currentOffset / circumference * 100);
    
    // 动画持续时间（毫秒）
    const duration = 800;
    const startTime = performance.now();
    
    // 使用requestAnimationFrame实现平滑动画
    function animate(currentTime) {
        const elapsedTime = currentTime - startTime;
        const progress = Math.min(elapsedTime / duration, 1);
        
        // 使用缓动函数使动画更自然
        const easeProgress = progress < 0.5 
            ? 4 * progress * progress * progress 
            : 1 - Math.pow(-2 * progress + 2, 3) / 2;
        
        // 计算当前应该显示的百分比
        const currentDisplayPercentage = currentPercentage + (targetPercentage - currentPercentage) * easeProgress;
        const offset = circumference - (currentDisplayPercentage / 100) * circumference;
        
        circle.style.strokeDashoffset = offset;
        
        // 更新百分比文本
        const percentageElement = document.getElementById(elementId.replace('progress', 'usage'));
        if (percentageElement) {
            percentageElement.textContent = `${Math.round(currentDisplayPercentage)}%`;
        }
        
        // 根据使用率改变颜色
        if (currentDisplayPercentage > 80) {
            circle.setAttribute('stroke', '#ef4444'); // 红色
        } else if (currentDisplayPercentage > 50) {
            circle.setAttribute('stroke', '#f59e0b'); // 黄色
        } else {
            // 恢复默认颜色
            if (elementId === 'cpu-progress') circle.setAttribute('stroke', '#3b82f6');
            if (elementId === 'mem-progress') circle.setAttribute('stroke', '#10b981');
            if (elementId === 'disk-progress') circle.setAttribute('stroke', '#8b5cf6');
        }
        
        // 继续动画直到完成
        if (progress < 1) {
            requestAnimationFrame(animate);
        }
    }
    
    // 开始动画
    requestAnimationFrame(animate);
}

// 网络IO图表相关变量
let networkChart = null;
let networkData = {
    labels: [],
    sent: [],
    recv: []
};
const MAX_DATA_POINTS = 30; // 最多显示30个数据点

// 初始化网络IO图表
function initNetworkChart() {
    const ctx = document.getElementById('network-speed-chart').getContext('2d');
    
    networkChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: networkData.labels,
            datasets: [
                {
                    label: '上传速度',
                    data: networkData.sent,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                },
                {
                    label: '下载速度',
                    data: networkData.recv,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y} KB/s`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: '时间'
                    },
                    grid: {
                        display: false
                    }
                },
                y: {
                    display: true,
                    title: {
                        display: true,
                        text: '速度 (KB/s)'
                    },
                    beginAtZero: true
                }
            },
            interaction: {
                intersect: false,
                mode: 'nearest'
            }
        }
    });
}

// 更新网络IO数据
function updateNetworkData(stats) {
    if (!stats.network) return;
    
    const network = stats.network;
    const now = new Date().toLocaleTimeString();
    
    // 添加新数据点
    networkData.labels.push(now);
    networkData.sent.push(network.sent_speed);
    networkData.recv.push(network.recv_speed);
    
    // 限制数据点数量
    if (networkData.labels.length > MAX_DATA_POINTS) {
        networkData.labels.shift();
        networkData.sent.shift();
        networkData.recv.shift();
    }
    
    // 更新统计信息
    document.getElementById('net-sent-speed').textContent = `${network.sent_speed} KB/s`;
    document.getElementById('net-recv-speed').textContent = `${network.recv_speed} KB/s`;
    document.getElementById('net-sent-total').textContent = `${network.bytes_sent} MB`;
    document.getElementById('net-recv-total').textContent = `${network.bytes_recv} MB`;
    document.getElementById('net-errors').textContent = network.errors_in + network.errors_out;
    document.getElementById('net-drops').textContent = network.drops_in + network.drops_out;
    
    // 更新图表
    if (networkChart) {
        networkChart.update();
    }
}

function updateSystemStats() {
    fetch('/api/system_stats')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.data) {
                const stats = data.data;
                    
                // 更新CPU信息
                updateProgressCircle('cpu-progress', stats.cpu.usage);
                document.getElementById('cpu-usage').textContent = `${stats.cpu.usage}%`;
                document.getElementById('cpu-cores').textContent = 
                    `${stats.cpu.physical_cores}物理 / ${stats.cpu.logical_cores}逻辑`;
                    
                // 更新内存信息
                updateProgressCircle('mem-progress', stats.memory.usage);
                document.getElementById('mem-usage').textContent = `${stats.memory.usage}%`;
                document.getElementById('mem-details').textContent = 
                    `${stats.memory.used}/${stats.memory.total} GB`;
                
                // 更新磁盘信息
                updateProgressCircle('disk-progress', stats.disk.usage);
                document.getElementById('disk-usage').textContent = `${stats.disk.usage}%`;
                document.getElementById('disk-details').textContent = 
                    `${stats.disk.used}/${stats.disk.total} GB`;
                    
                // 更新系统负载 (仅Unix系统)
                if (stats.load_avg) {
                    document.getElementById('load-average-container').style.display = 'block';
                    document.getElementById('load-1').textContent = stats.load_avg[0];
                    document.getElementById('load-5').textContent = stats.load_avg[1];
                    document.getElementById('load-15').textContent = stats.load_avg[2];
                }

                updateNetworkData(stats);
            }
        })
        .catch(error => console.error('获取系统状态失败:', error));
}

// 启动机器人
function startBot() {
    fetch('/api/start_bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('启动机器人失败:', error);
            showNotification('启动机器人失败，请检查网络连接', 'error');
        });
}

// 停止机器人
function stopBot() {
    fetch('/api/stop_bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('停止机器人失败:', error);
            showNotification('停止机器人失败，请检查网络连接', 'error');
        });
}

// 重启机器人
function restartBot() {
    fetch('/api/restart_bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                fetchBotStatus();
            }
        })
        .catch(error => {
            console.error('重启机器人失败:', error);
            showNotification('重启机器人失败，请检查网络连接', 'error');
        });
}

// 显示通知
function showNotification(message, type = 'info') {
    // 创建通知元素
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-500' : 
                   type === 'error' ? 'bg-red-500' : 
                   'bg-blue-500';
    const icon = type === 'success' ? 'fa-check' : 
                type === 'error' ? 'fa-exclamation-triangle' : 
                'fa-info';
    
    notification.className = `fixed top-4 right-4 p-4 rounded-lg shadow-lg z-50 max-w-sm transform transition-transform duration-300 translate-x-full ${bgColor} text-white`;
    notification.innerHTML = `
        <div class="flex items-center">
            <i class="fa ${icon} mr-3"></i>
            <span class="flex-1">${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 text-white hover:text-gray-200">
                <i class="fa fa-times"></i>
            </button>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // 显示通知
    setTimeout(() => {
        notification.classList.remove('translate-x-full');
    }, 100);
    
    // 5秒后隐藏并移除
    setTimeout(() => {
        notification.classList.add('translate-x-full');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 5000);
}

const adminForm = document.getElementById('admin-form');
if (adminForm) {
    adminForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        const data = {
            username: formData.get('username'),
            current_password: formData.get('current_password'),
            new_password: formData.get('new_password')
        };
        
        if (data.new_password && data.new_password !== formData.get('confirm_password')) {
            showNotification('新密码和确认密码不匹配', 'error');
            return;
        }
        
        fetch('/api/update_admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                // 更新页面上的用户名显示
                const usernameElements = document.querySelectorAll('.username-display');
                usernameElements.forEach(el => {
                    el.textContent = data.username || formData.get('username');
                });
            }
        })
        .catch(error => {
            console.error('更新账号信息失败:', error);
            showNotification('更新账号信息失败，请检查网络连接', 'error');
        });
    });
}

// 计算运行时间
function updateUptime() {
    const startTime = new Date();
    setInterval(() => {
        const now = new Date();
        const diff = now - startTime;
        const hours = Math.floor(diff / 3600000);
        const minutes = Math.floor((diff % 3600000) / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        
        const uptimeElement = document.getElementById('uptime');
        if (uptimeElement) {
            uptimeElement.textContent = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
    }, 1000);
}

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    // 开始状态轮询
    setInterval(fetchBotStatus, 3000);
    fetchBotStatus();
    
    loadAccounts();
    
    // 初始化运行时间
    updateUptime();

    // 获取公告
    get_announcement();
    
    const hash = window.location.hash.split("#")[1]
    if (hash) {
        showSection(hash);
    } else {
        // 设置默认激活的导航项
        const defaultNav = document.querySelector('.nav-item.active');
        if (defaultNav) {
            defaultNav.click();
        }
    }
    
    // 添加用户名显示类
    const usernameElements = document.querySelectorAll('.username-display');
    usernameElements.forEach(el => {
        el.textContent = '{{ session.username }}';
    });

    setTimeout(checkForUpdates, 2000);

    updateSystemStats();
    setInterval(updateSystemStats, 2000);
    initImageBed();

    loadInstalledPlugins()
    getPluginList()
    initGitHubDiscussions();
    
    // 在显示GitHub讨论区时重新加载
    const githubSection = document.getElementById('github_discussions');
    if (githubSection) {
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                    if (githubSection.style.display !== 'none') {
                        initGitHubDiscussions();
                    }
                }
            });
        });
        
        observer.observe(githubSection, { attributes: true });
    }
    initNetworkChart();
});