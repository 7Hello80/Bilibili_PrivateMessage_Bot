let layuiForm = null;
// 插件商店功能
let currentPluginSearchKeyword = '';
let installedPlugins = [];
let onlinePlugins = [];
let botRunning = false;           // 机器人进程是否在运行
let pluginDetailName = null;      // 当前打开详情的插件名
let pluginDetailData = null;      // 当前插件详情数据缓存

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

// ================= 侧边栏 / 导航 =================

// 移动端抽屉
// 顶栏菜单按钮兼容旧 id（mobile-menu-btn）与新 id（mobile-menu-button）
function getMobileMenuButton() {
    return document.querySelector('#mobile-menu-button, #mobile-menu-btn, .mobile-menu-button');
}

function openSidebar() {
    document.body.classList.add('sidebar-open');
    const btn = getMobileMenuButton();
    if (btn) btn.setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
    document.body.classList.remove('sidebar-open');
    const btn = getMobileMenuButton();
    if (btn) btn.setAttribute('aria-expanded', 'false');
}

// 桌面端折叠
function toggleSidebarCollapse() {
    const collapsed = document.body.classList.toggle('is-collapsed');
    try {
        localStorage.setItem('bilibot.sidebarCollapsed', collapsed ? '1' : '0');
    } catch (e) { /* 忽略隐私模式下的存储异常 */ }
}

document.addEventListener('DOMContentLoaded', function() {
    const menuButtons = document.querySelectorAll('#mobile-menu-btn, #mobile-menu-button, .mobile-menu-button');
    menuButtons.forEach(button => {
        button.setAttribute('aria-expanded', 'false');
        button.addEventListener('click', function() {
            if (document.body.classList.contains('sidebar-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
    });

    const overlay = document.getElementById('overlay');
    if (overlay) {
        overlay.addEventListener('click', closeSidebar);
    }

    const collapseBtn = document.getElementById('sidebar-toggle');
    if (collapseBtn) {
        collapseBtn.addEventListener('click', toggleSidebarCollapse);
        try {
            if (localStorage.getItem('bilibot.sidebarCollapsed') === '1') {
                document.body.classList.add('is-collapsed');
            }
        } catch (e) { /* 忽略 */ }
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeSidebar();
    });
});

// 各区块的标题，用于顶栏面包屑
const SECTION_LABELS = {
    dashboard: '控制台',
    accounts: '多账号管理',
    github_discussions: 'GitHub 讨论区',
    plugins: '插件商店',
    logs: '运行日志',
    image_bed: '图床管理',
    admin: '账号设置',
    about: '关于我们'
};

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
                botRunning = !!data.bot_running;
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

// 更新已安装插件列表(状态徽章: 运行中/未加载/已禁用/失败/机器人未运行)
function updateInstalledPluginsList() {
    const container = document.getElementById('installed-plugins-list');
    if (!container) return;

    if (!installedPlugins || installedPlugins.length === 0) {
        container.innerHTML = `
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-solid fa-puzzle-piece"></i></div>
                <strong>暂无已安装插件</strong>
                <p>在右侧插件市场中搜索并安装插件</p>
            </div>
        `;
        return;
    }

    container.innerHTML = installedPlugins.map(plugin => {
        // 状态徽章逻辑
        let statusBadge = '';
        let dotClass = 'dot';
        if (!botRunning) {
            statusBadge = '<span class="badge badge-neutral">机器人未运行</span>';
            dotClass = 'dot';
        } else if (plugin.error) {
            statusBadge = `<span class="badge badge-danger" style="cursor:pointer" title="点击查看失败原因"
                onclick="showPluginError('${plugin.name.replace(/'/g, "\\'")}', '${(plugin.error || '').replace(/'/g, "\\'").replace(/\n/g, ' ')}')">加载失败</span>`;
            dotClass = 'dot red';
        } else if (plugin.loaded) {
            statusBadge = '<span class="badge badge-success">运行中</span>';
            dotClass = 'dot green';
        } else if (plugin.enabled) {
            statusBadge = '<span class="badge badge-warning">未加载</span>';
            dotClass = 'dot amber';
        } else {
            statusBadge = '<span class="badge badge-neutral">已禁用</span>';
            dotClass = 'dot';
        }

        const updateBtn = plugin.has_update
            ? `<button class="btn btn-sm btn-warning" onclick="updatePlugin('${plugin.name}')">
                   <i class="fa-solid fa-arrow-up"></i>更新 v${plugin.latest_version || ''}
               </button>`
            : '';

        const deps = (plugin.metadata.dependencies || []);
        const depsBlock = deps.length > 0 ? `
            <div class="row-wrap mt-3">
                <span class="field-hint">依赖</span>
                ${deps.map(dep => `<span class="chip">${typeof dep === 'string' ? dep : (dep.name || '')}</span>`).join('')}
            </div>
        ` : '';

        return `
        <article class="list-item">
            <div class="list-item-head">
                <div class="list-item-title">
                    <span class="${dotClass}" aria-hidden="true"></span>
                    <h4>${plugin.metadata.name}</h4>
                    <span class="badge badge-info">v${plugin.metadata.version}</span>
                    ${statusBadge}
                </div>
                <div class="list-actions">
                    <button class="btn btn-sm ${plugin.enabled ? 'btn-warning' : 'btn-success'}"
                            onclick="togglePlugin('${plugin.name}', ${!plugin.enabled})">
                        <i class="fa-solid ${plugin.enabled ? 'fa-pause' : 'fa-play'}"></i>${plugin.enabled ? '禁用' : '启用'}
                    </button>
                    <button class="btn btn-sm btn-secondary" onclick="reloadPlugin('${plugin.name}')">
                        <i class="fa-solid fa-arrows-rotate"></i>重载
                    </button>
                    <button class="btn btn-sm btn-info" onclick="openPluginDetail('${plugin.name}')">
                        <i class="fa-solid fa-circle-info"></i>详情
                    </button>
                    <button class="btn btn-sm btn-ghost" onclick="backupPlugin('${plugin.name}')">
                        <i class="fa-solid fa-hard-drive"></i>备份
                    </button>
                    ${updateBtn}
                    <button class="btn btn-sm btn-danger" onclick="uninstallPlugin('${plugin.name}')">
                        <i class="fa-solid fa-trash"></i>卸载
                    </button>
                </div>
            </div>

            <p class="list-item-desc">${plugin.metadata.description || '暂无描述'}</p>

            <div class="list-item-meta">
                <div><span>作者</span><strong>${plugin.metadata.author || '未知'}</strong></div>
                <div><span>类型</span><strong>${plugin.metadata.type || 'base'}</strong></div>
                <div><span>命令</span><strong>${(plugin.commands || []).map(c => '!' + c[0]).join(' ') || '无'}</strong></div>
            </div>
            ${depsBlock}
        </article>
        `;
    }).join('');
}

// 显示插件加载失败详情
function showPluginError(name, error) {
    layer.alert(error || '加载失败', {
        icon: 2,
        title: `插件 ${name} 加载失败原因`
    });
}

// 搜索插件
function searchPlugins() {
    const keyword = document.getElementById('plugin-search').value;
    currentPluginSearchKeyword = keyword;
    
    if (!keyword.trim()) {
        document.getElementById('online-plugins-list').innerHTML = `
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-solid fa-magnifying-glass"></i></div>
                <strong>还没有搜索</strong>
                <p>在上方输入关键词搜索插件</p>
            </div>
        `;
        return;
    }

    document.getElementById('online-plugins-list').innerHTML = `
        <div class="loading-row"><i class="fa-solid fa-circle-notch fa-spin"></i>搜索中…</div>
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
                    <div class="empty-state compact">
                        <div class="empty-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
                        <strong>搜索失败</strong>
                        <p>请稍后重试</p>
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
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-solid fa-box-open"></i></div>
                <strong>没有找到相关插件</strong>
                <p>换个关键词再试试</p>
            </div>
        `;
        return;
    }

    container.innerHTML = onlinePlugins.map(plugin => {
        const isInstalled = installedPlugins.some(p => p.name === plugin.name);
        const deps = plugin.dependencies || [];

        return `
        <article class="list-item">
            <div class="list-item-head">
                <div class="list-item-title">
                    <h4>${plugin.name}</h4>
                    <span class="badge badge-info">v${plugin.version || '1.0.0'}</span>
                    ${isInstalled ? '<span class="badge badge-success">已安装</span>' : ''}
                </div>
                <div class="list-actions">
                    ${!isInstalled ? `
                    <button class="btn btn-sm btn-success" onclick="installPlugin('${plugin.full_name}', '${plugin.name}')">
                        <i class="fa-solid fa-download"></i>安装
                    </button>
                    ` : ''}
                    <a class="btn btn-sm btn-ghost" href="${plugin.html_url}" target="_blank" rel="noopener">
                        <i class="fa-solid fa-arrow-up-right-from-square"></i>查看
                    </a>
                </div>
            </div>

            <p class="list-item-desc">${plugin.description || '暂无描述'}</p>

            <div class="list-item-meta" style="grid-template-columns:repeat(2,minmax(0,1fr));">
                <div><span>作者</span><strong>${plugin.author || plugin.owner || '未知'}</strong></div>
                <div><span>星标</span><strong>${plugin.stars || 0}</strong></div>
                <div><span>Fork</span><strong>${plugin.forks || 0}</strong></div>
                <div><span>更新</span><strong>${formatDate(plugin.updated_at)}</strong></div>
            </div>

            ${deps.length > 0 ? `
            <div class="row-wrap mt-3">
                <span class="field-hint">依赖</span>
                ${deps.map(dep => `<span class="chip">${dep}</span>`).join('')}
            </div>
            ` : ''}
        </article>
        `;
    }).join('');
}

function getPluginList() {
    document.getElementById('online-plugins-list').innerHTML = `
        <div class="loading-row"><i class="fa-solid fa-circle-notch fa-spin"></i>加载中…</div>
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
                    <div class="empty-state compact">
                        <div class="empty-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
                        <strong>获取失败</strong>
                        <p>请检查网络后重试</p>
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
    layer.confirm(`确定要安装插件 "${pluginName}" 吗？<br><span style="color:#dc2626;font-size:12px;">⚠ 插件以代码形式运行且与机器人同进程，请只安装可信来源的插件</span>`, {
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
            showNotification(data.message, data.success ? (data.bot_not_running ? 'warning' : 'success') : 'error');
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
    layer.confirm(`确定要卸载插件 "${pluginName}" 吗？<br><span style="color:#6b7280;font-size:12px;">卸载前会自动备份，可在详情页恢复</span>`, {
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
        showNotification(data.message, data.success ? (data.bot_not_running ? 'warning' : 'success') : 'error');
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
        showNotification(data.message, data.success ? (data.bot_not_running ? 'warning' : 'success') : 'error');
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

// ================= 插件详情 =================

// 打开插件详情模态框
function openPluginDetail(name) {
    pluginDetailName = name;
    pluginDetailData = null;
    document.getElementById('plugin-detail-modal').classList.remove('hidden');
    document.getElementById('plugin-detail-title').textContent = name;
    document.getElementById('plugin-detail-version').textContent = '加载中...';
    document.getElementById('plugin-detail-status-badge').textContent = '';
    document.getElementById('plugin-detail-update-badge').classList.add('hidden');

    fetch('/api/plugins/detail/' + encodeURIComponent(name))
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showNotification(data.message || '获取插件详情失败', 'error');
                return;
            }
            pluginDetailData = data;
            renderPluginDetailInfo(data);
        })
        .catch(error => {
            console.error('获取插件详情失败:', error);
            showNotification('获取插件详情失败', 'error');
        });

    // 默认显示信息 tab
    switchPluginTab('info');
}

// 渲染详情-信息 tab
function renderPluginDetailInfo(data) {
    const plugin = data.plugin || {};
    const metadata = plugin.metadata || {};
    const status = data.status || {};

    document.getElementById('plugin-detail-version').textContent = 'v' + (metadata.version || '1.0.0');

    // 状态徽章
    const badge = document.getElementById('plugin-detail-status-badge');
    if (!data.bot_running) {
        badge.textContent = '机器人未运行';
        badge.className = 'badge badge-neutral';
    } else if (status.error) {
        badge.textContent = '加载失败';
        badge.className = 'badge badge-danger';
    } else if (status.loaded) {
        badge.textContent = '运行中';
        badge.className = 'badge badge-success';
    } else if (metadata.enabled) {
        badge.textContent = '未加载';
        badge.className = 'badge badge-warning';
    } else {
        badge.textContent = '已禁用';
        badge.className = 'badge badge-neutral';
    }

    // 快捷操作按钮状态(启用/禁用)
    const toggleBtn = document.getElementById('plugin-detail-toggle-btn');
    if (toggleBtn) {
        toggleBtn.className = 'btn btn-sm ' + (metadata.enabled ? 'btn-warning' : 'btn-success');
        toggleBtn.innerHTML = metadata.enabled
            ? '<i class="fa-solid fa-pause"></i>禁用'
            : '<i class="fa-solid fa-play"></i>启用';
    }

    // API 测试提示: 已注册路由
    const routesHint = document.getElementById('plugin-api-routes-hint');
    if (routesHint) {
        routesHint.textContent = (status.api_routes || []).join('  ') || '无';
    }

    const infoEl = document.getElementById('plugin-detail-info');
    const commands = (status.commands || []).map(c => `!${c[0]}${c[1] ? ' - ' + c[1] : ''}`).join('\n') || '无';
    const apiRoutes = (status.api_routes || []).map(r => `/api/plugins/api/${pluginDetailName}${r}`).join('\n') || '无';
    const backups = (data.backups || []);
    const backupsHtml = backups.length > 0
        ? backups.map(b => `
            <div class="backup-row">
                <span class="mono">${b.file}<em>${formatFileSize(b.size)}</em></span>
                <button class="btn btn-sm btn-ghost" onclick="restorePlugin('${pluginDetailName}', '${b.file}')">
                    <i class="fa-solid fa-clock-rotate-left"></i>恢复
                </button>
            </div>`).join('')
        : '<p class="field-hint" style="margin:6px 0;">暂无备份</p>';

    infoEl.innerHTML = `
        <div class="info-list">
            <div class="info-row"><span>描述</span><strong>${metadata.description || '暂无描述'}</strong></div>
            <div class="info-row"><span>作者</span><strong>${metadata.author || '未知'}</strong></div>
            <div class="info-row"><span>类型</span><strong>${metadata.type || 'base'}</strong></div>
            <div class="info-row"><span>加载顺序</span><strong>${metadata.load_order || 0}</strong></div>
            <div class="info-row"><span>绕过关注检查</span><strong>${metadata.bypass_follow_check ? '是' : '否'}</strong></div>
            <div class="info-row"><span>仓库</span><strong>${metadata.repository || '未配置'}</strong></div>
        </div>
        ${status.error ? `<div class="notice notice-danger" style="margin-top:4px;">
            <div class="notice-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
            <div class="notice-body"><h3>加载失败原因</h3><p>${status.error}</p></div>
        </div>` : ''}
        <div class="detail-section">
            <h4 class="field-label">已注册命令</h4>
            <pre class="code-panel">${commands}</pre>
        </div>
        <div class="detail-section">
            <h4 class="field-label">插件 API 路由</h4>
            <pre class="code-panel">${apiRoutes}</pre>
        </div>
        <div class="detail-section">
            <div class="row-between mb-2">
                <h4 class="field-label" style="margin:0;">备份列表</h4>
                <button class="btn btn-sm btn-secondary" onclick="backupPlugin('${pluginDetailName}')">
                    <i class="fa-solid fa-hard-drive"></i>立即备份
                </button>
            </div>
            ${backupsHtml}
        </div>
    `;
}

function hidePluginDetailModal() {
    document.getElementById('plugin-detail-modal').classList.add('hidden');
}

// 详情页快捷启用/禁用
function togglePluginFromDetail() {
    if (!pluginDetailName || !pluginDetailData) return;
    const enabled = pluginDetailData.plugin.metadata.enabled;
    fetch('/api/plugins/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginDetailName, enabled: !enabled })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? (data.bot_not_running ? 'warning' : 'success') : 'error');
        if (data.success) {
            loadInstalledPlugins();
            openPluginDetail(pluginDetailName);
        }
    })
    .catch(error => {
        console.error('切换插件状态失败:', error);
        showNotification('切换插件状态失败', 'error');
    });
}

// API 测试: 直接调用插件注册的 API 路由
function testPluginApi() {
    if (!pluginDetailName) return;
    const pathEl = document.getElementById('plugin-api-path');
    const path = (pathEl.value || '').trim();
    if (!path) {
        showNotification('请输入 API 路径', 'error');
        return;
    }
    const method = document.getElementById('plugin-api-method').value;
    const resultEl = document.getElementById('plugin-api-result');
    resultEl.textContent = '请求中...';

    const options = { method: method };
    if (method === 'POST') {
        options.headers = { 'Content-Type': 'application/json' };
        const bodyText = document.getElementById('plugin-api-body').value.trim();
        if (bodyText) {
            try {
                JSON.parse(bodyText);
            } catch (e) {
                showNotification('请求体 JSON 格式错误: ' + e.message, 'error');
                return;
            }
            options.body = bodyText;
        }
    }
    const fullPath = path.startsWith('/') ? path : '/' + path;
    fetch('/api/plugins/api/' + encodeURIComponent(pluginDetailName) + fullPath, options)
        .then(response => response.text())
        .then(text => {
            try {
                resultEl.textContent = JSON.stringify(JSON.parse(text), null, 2);
            } catch (e) {
                resultEl.textContent = text;
            }
        })
        .catch(error => {
            resultEl.textContent = '请求失败: ' + error.message;
        });
}

// 切换详情 tab(README 懒加载)
function switchPluginTab(tab) {
    // tab 高亮
    document.querySelectorAll('.plugin-detail-tab').forEach(btn => {
        btn.classList.toggle('is-active', btn.getAttribute('data-plugin-tab') === tab);
    });
    // 内容显示
    document.querySelectorAll('.plugin-detail-content').forEach(el => el.classList.add('hidden'));
    const target = document.getElementById('plugin-tab-' + tab);
    if (target) target.classList.remove('hidden');

    if (!pluginDetailName) return;
    if (tab === 'readme' && pluginDetailData) {
        document.getElementById('plugin-detail-readme').textContent =
            pluginDetailData.readme || '暂无 README 内容';
    } else if (tab === 'config') {
        loadPluginConfigTab(pluginDetailName);
    } else if (tab === 'logs') {
        loadPluginLogs(pluginDetailName);
    } else if (tab === 'metrics') {
        loadPluginMetrics(pluginDetailName);
    } else if (tab === 'apitest') {
        // 刷新已注册路由提示
        if (pluginDetailData) {
            const hintEl = document.getElementById('plugin-api-routes-hint');
            if (hintEl) {
                hintEl.textContent = ((pluginDetailData.status || {}).api_routes || []).join('  ') || '无';
            }
        }
    } else if (tab === 'source') {
        loadPluginSourceFile(pluginDetailName);
    }
}

// ================= 配置编辑 =================

function loadPluginConfigTab(name) {
    fetch('/api/plugins/config?plugin_name=' + encodeURIComponent(name))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('plugin-config-editor').value =
                    JSON.stringify(data.config, null, 2);
                document.getElementById('plugin-config-error').classList.add('hidden');
            } else {
                showNotification(data.message || '加载配置失败', 'error');
            }
        })
        .catch(error => {
            console.error('加载配置失败:', error);
            showNotification('加载配置失败', 'error');
        });
}

function savePluginConfig() {
    if (!pluginDetailName) return;
    const raw = document.getElementById('plugin-config-editor').value;
    let config;
    try {
        config = JSON.parse(raw);
    } catch (e) {
        const errEl = document.getElementById('plugin-config-error');
        errEl.textContent = 'JSON 格式错误: ' + e.message;
        errEl.classList.remove('hidden');
        return;
    }
    document.getElementById('plugin-config-error').classList.add('hidden');

    fetch('/api/plugins/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginDetailName, config: config })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success
            ? (data.bot_not_running ? 'warning' : 'success') : 'error');
    })
    .catch(error => {
        console.error('保存配置失败:', error);
        showNotification('保存配置失败', 'error');
    });
}

// ================= 日志与指标 =================

function loadPluginLogs(name) {
    document.getElementById('plugin-detail-file-logs').textContent = '加载中...';
    document.getElementById('plugin-detail-bot-logs').textContent = '加载中...';
    fetch('/api/plugins/logs?plugin_name=' + encodeURIComponent(name))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById('plugin-detail-file-logs').textContent =
                    data.file_logs.length ? data.file_logs.join('\n') : '(暂无日志)';
                document.getElementById('plugin-detail-bot-logs').textContent =
                    data.bot_logs.length ? data.bot_logs.join('\n') : '(暂无相关日志)';
            } else {
                showNotification(data.message || '获取日志失败', 'error');
            }
        })
        .catch(error => {
            console.error('获取插件日志失败:', error);
            showNotification('获取插件日志失败', 'error');
        });
}

function loadPluginMetrics(name) {
    const cardsEl = document.getElementById('plugin-detail-metric-cards');
    const rawEl = document.getElementById('plugin-detail-metrics');
    if (cardsEl) cardsEl.innerHTML = '<div class="loading-row" style="grid-column:1/-1;"><i class="fa-solid fa-circle-notch fa-spin"></i>加载中…</div>';
    if (rawEl) rawEl.textContent = '加载中...';
    fetch('/api/plugins/metrics?plugin=' + encodeURIComponent(name))
        .then(response => response.json())
        .then(data => {
            if (!data || !data.success) {
                if (cardsEl) cardsEl.innerHTML = '<p class="field-hint" style="grid-column:1/-1;">' +
                    ((data && data.message) || '获取指标失败(机器人未运行?)') + '</p>';
                if (rawEl) rawEl.textContent = '(无法获取指标)';
                return;
            }
            const pluginData = (data.data || {})[name] || {};
            const metrics = pluginData.metrics || {};
            const entries = Object.entries(metrics);
            if (cardsEl) {
                cardsEl.innerHTML = entries.length
                    ? entries.map(([k, v]) => `
                        <div class="stat-card">
                            <div class="stat-top">
                                <span class="stat-label">${k}</span>
                            </div>
                            <div class="stat-value is-text">${typeof v === 'object' ? JSON.stringify(v) : v}</div>
                        </div>`).join('')
                    : '<p class="field-hint" style="grid-column:1/-1;">该插件未注册指标</p>';
            }
            if (rawEl) rawEl.textContent = JSON.stringify(pluginData.dashboard || {}, null, 2);
        })
        .catch(error => {
            console.error('获取插件指标失败:', error);
            if (cardsEl) cardsEl.innerHTML = '<p class="field-error" style="grid-column:1/-1;">获取指标失败</p>';
            if (rawEl) rawEl.textContent = '获取指标失败';
        });
}

// ================= 备份 / 恢复 / 更新 =================

function backupPlugin(pluginName) {
    fetch('/api/plugins/backup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName })
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.success ? 'success' : 'error');
        if (data.success && pluginDetailName === pluginName) {
            openPluginDetail(pluginName);  // 刷新备份列表
        }
    })
    .catch(error => {
        console.error('备份插件失败:', error);
        showNotification('备份插件失败', 'error');
    });
}

function restorePlugin(pluginName, backupFile) {
    layer.confirm(`确定要从备份 "${backupFile}" 恢复插件 "${pluginName}" 吗？当前版本将自动备份。`, {
        icon: 3,
        title: '确认恢复'
    }, function(index) {
        fetch('/api/plugins/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin_name: pluginName, backup_file: backupFile })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) {
                loadInstalledPlugins();
                if (pluginDetailName === pluginName) openPluginDetail(pluginName);
            }
        })
        .catch(error => {
            console.error('恢复插件失败:', error);
            showNotification('恢复插件失败', 'error');
        });
        layer.close(index);
    });
}

function checkPluginUpdate(pluginName) {
    showNotification('正在检查更新...', 'info');
    fetch('/api/plugins/check_update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_name: pluginName })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            showNotification(data.message || '检查更新失败', 'error');
            return;
        }
        if (data.has_update) {
            const badge = document.getElementById('plugin-detail-update-badge');
            badge.textContent = `可更新到 v${data.latest_version}`;
            badge.classList.remove('hidden');
            showNotification(`发现新版本 v${data.latest_version}(当前 v${data.local_version})`, 'warning');
        } else {
            showNotification(data.message || '已是最新版本', 'success');
        }
    })
    .catch(error => {
        console.error('检查更新失败:', error);
        showNotification('检查更新失败', 'error');
    });
}

function updatePlugin(pluginName) {
    layer.confirm(`确定要更新插件 "${pluginName}" 吗？更新前会自动备份当前版本。`, {
        icon: 3,
        title: '确认更新'
    }, function(index) {
        fetch('/api/plugins/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin_name: pluginName })
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) loadInstalledPlugins();
        })
        .catch(error => {
            console.error('更新插件失败:', error);
            showNotification('更新插件失败', 'error');
        });
        layer.close(index);
    });
}

// ================= 导入 / 全部重载 =================

function importPluginZip(input) {
    if (!input.files || !input.files.length) return;
    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);

    layer.confirm(`确定要导入插件 "${file.name}" 吗？插件将以代码形式运行，请只导入可信来源！`, {
        icon: 3,
        title: '确认导入'
    }, function(index) {
        fetch('/api/plugins/import', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) loadInstalledPlugins();
        })
        .catch(error => {
            console.error('导入插件失败:', error);
            showNotification('导入插件失败', 'error');
        });
        layer.close(index);
    });
    input.value = '';
}

function reloadAllPlugins() {
    layer.confirm('确定要重载全部插件吗？', {
        icon: 3,
        title: '确认重载'
    }, function(index) {
        fetch('/api/plugins/reload_all', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                showNotification(data.message, data.success
                    ? (data.bot_not_running ? 'warning' : 'success') : 'error');
                if (data.success) loadInstalledPlugins();
            })
            .catch(error => {
                console.error('重载全部插件失败:', error);
                showNotification('重载全部插件失败', 'error');
            });
        layer.close(index);
    });
}

// ================= 源码编辑 =================

// 插件目录下可编辑文件缓存: {相对路径: 内容}
let pluginSourceFiles = {};

// 加载插件目录下的文件列表并填充下拉框(实际存在的文件, 非固定文件)
function loadPluginSourceFile(name) {
    if (!name) return;
    fetch('/api/plugins/edit/' + encodeURIComponent(name))
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showNotification(data.message || '加载源码失败', 'error');
                return;
            }
            pluginSourceFiles = data.files || {};
            const select = document.getElementById('plugin-source-file');
            const names = Object.keys(pluginSourceFiles).sort();
            if (names.length) {
                select.innerHTML = names.map(f =>
                    `<option value="${f}">${f}</option>`).join('');
                // 默认选中 main.py
                if (names.indexOf('main.py') >= 0) {
                    select.value = 'main.py';
                }
            } else {
                select.innerHTML = '<option value="">(无可编辑文件)</option>';
            }
            updateSourceEditor();
            const skipped = data.skipped || [];
            if (skipped.length) {
                showNotification('以下大文件(>256KB)已跳过编辑: ' + skipped.join(', '), 'warning');
            }
        })
        .catch(error => {
            console.error('加载源码失败:', error);
            showNotification('加载源码失败', 'error');
        });
}

// 切换下拉框文件时更新编辑器内容
function updateSourceEditor() {
    const select = document.getElementById('plugin-source-file');
    const editor = document.getElementById('plugin-source-editor');
    if (!select || !editor) return;
    const fname = select.value;
    editor.value = (fname && pluginSourceFiles[fname] !== undefined)
        ? pluginSourceFiles[fname] : '';
    editor.readOnly = !fname;
    const errEl = document.getElementById('plugin-source-error');
    if (errEl) errEl.classList.add('hidden');
}

function savePluginSource() {
    if (!pluginDetailName) return;
    const select = document.getElementById('plugin-source-file');
    const fname = select.value;
    if (!fname) {
        showNotification('没有可编辑的文件', 'error');
        return;
    }
    const content = document.getElementById('plugin-source-editor').value;

    fetch('/api/plugins/edit/' + encodeURIComponent(pluginDetailName), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: fname, content: content })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            pluginSourceFiles[fname] = content;  // 更新本地缓存
            document.getElementById('plugin-source-error').classList.add('hidden');
            showNotification(data.message, 'success');
            loadInstalledPlugins();
        } else {
            const errEl = document.getElementById('plugin-source-error');
            errEl.textContent = data.message || '保存失败';
            errEl.classList.remove('hidden');
            showNotification(data.message || '保存失败', 'error');
        }
    })
    .catch(error => {
        console.error('保存源码失败:', error);
        showNotification('保存源码失败', 'error');
    });
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
        targetSection.classList.add('active');
    }

    // 更新导航项状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });

    // 找到被点击的导航项并激活它
    const clickedNav = document.querySelector(`[href="#${sectionId}"]`);
    if (clickedNav) {
        clickedNav.classList.add('active');
    }

    // 更新顶栏面包屑
    const crumb = document.getElementById('page-crumb');
    if (crumb && SECTION_LABELS[sectionId]) {
        crumb.textContent = SECTION_LABELS[sectionId];
    }

    // 特殊处理：如果是日志部分，开始轮询日志
    if (sectionId === 'logs') {
        startLogPolling();
    } else {
        stopLogPolling();
    }

    // 在移动端选择后关闭抽屉
    closeSidebar();

    // 记录当前区块，刷新后保持位置
    try {
        if (location.hash !== '#' + sectionId) {
            history.replaceState(null, '', '#' + sectionId);
        }
    } catch (e) { /* 忽略 */ }
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
        btn.classList.remove('active');
    });

    const activeBtn = document.getElementById(`filter-${filter}`);
    if (activeBtn) {
        activeBtn.classList.add('active');
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
        logContainer.innerHTML = `
            <div class="empty-state" style="padding:32px 12px;">
                <div class="empty-icon" style="background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.08);color:#64748b;"><i class="fa-regular fa-file-lines"></i></div>
                <strong style="color:#94a3b8;">暂无日志</strong>
                <p>机器人启动后将在此输出运行记录</p>
            </div>`;
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
        logContainer.innerHTML = `
            <div class="empty-state" style="padding:32px 12px;">
                <div class="empty-icon" style="background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.08);color:#64748b;"><i class="fa-solid fa-magnifying-glass"></i></div>
                <strong style="color:#94a3b8;">没有匹配的日志</strong>
                <p>试试更换过滤条件或关键词</p>
            </div>`;
        updateLogStats(0, filteredLogs.length);
        return;
    }

    const escapeHtml = (text) => String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

    // 渲染日志条目
    logContainer.innerHTML = filteredLogs.map(log => {
        let logClass = 'info';
        let icon = 'fa-solid fa-circle-info';
        let label = 'INFO';

        if (log.includes('ERROR') || log.includes('错误') || log.includes('失败')) {
            logClass = 'error';
            icon = 'fa-solid fa-circle-exclamation';
            label = 'ERROR';
        } else if (log.includes('成功') || log.includes('SUCCESS')) {
            logClass = 'success';
            icon = 'fa-solid fa-circle-check';
            label = 'OK';
        } else if (log.includes('警告') || log.includes('WARNING')) {
            logClass = 'warning';
            icon = 'fa-solid fa-triangle-exclamation';
            label = 'WARN';
        } else if (log.includes('BOT:')) {
            logClass = 'bot';
            icon = 'fa-solid fa-robot';
            label = 'BOT';
        }

        // 转义后再做关键词高亮，避免日志内容里的 HTML 被解析
        let highlightedLog = escapeHtml(log);
        if (searchTerm) {
            const escapedTerm = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const regex = new RegExp(`(${escapedTerm})`, 'gi');
            highlightedLog = highlightedLog.replace(regex, '<mark>$1</mark>');
        }

        const safeAttr = escapeHtml(log);

        return `
            <div class="log-entry ${logClass}" data-log="${safeAttr}" title="点击复制日志内容">
                <div class="log-entry-head">
                    <i class="${icon}"></i>
                    <span class="log-tag">${label}</span>
                </div>
                <div class="log-entry-body">${highlightedLog}</div>
            </div>
        `;
    }).join('');

    // 点击复制（事件委托，避免内联字符串转义问题）
    logContainer.onclick = function(evt) {
        const entry = evt.target.closest('.log-entry');
        if (entry) {
            copyLogContent(entry.getAttribute('data-log') || '');
        }
    };

    updateLogStats(currentLogs.length, filteredLogs.length);

    // 自动滚动到底部
    if (autoScrollEnabled) {
        logContainer.scrollTop = logContainer.scrollHeight;
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
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragenter', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        // 只有当鼠标离开上传区域时才移除样式
        if (!uploadArea.contains(e.relatedTarget)) {
            uploadArea.classList.remove('dragover');
        }
    });

    uploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('dragover');
        
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
        const bar = document.getElementById('progress-bar');
        bar.style.width = '0%';
        bar.classList.remove('is-error');
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
        document.getElementById('progress-bar').classList.add('is-error');
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
        cancelBtn.className = 'btn btn-secondary';
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

    if (imagesCount) imagesCount.textContent = images ? images.length : 0;

    if (!images || images.length === 0) {
        container.classList.add('hidden');
        if (emptyMessage) emptyMessage.classList.remove('hidden');
        return;
    }

    container.classList.remove('hidden');
    if (emptyMessage) emptyMessage.classList.add('hidden');

    container.innerHTML = images.map(image => {
        const safeUrl = (image.url || '').replace(/'/g, "\\'");
        const name = image.name || '未命名';
        return `
        <figure class="image-card" tabindex="0"
                onclick="previewImage('${safeUrl}')"
                oncontextmenu="showImageContextMenu(event, '${safeUrl}'); return false;"
                onkeydown="if(event.key==='Enter'){previewImage('${safeUrl}');}">
            <div class="thumb">
                <img src="${image.url}" alt="${name}" loading="lazy" referrerpolicy="no-referrer">
            </div>
            <figcaption class="meta">
                <strong title="${name}">${name}</strong>
                <span>${image.upload_account || '未知用户'}</span>
                <span>${image.upload_time || ''}</span>
            </figcaption>
            <div class="overlay">
                <button type="button" title="复制 URL" aria-label="复制 URL"
                        onclick="event.stopPropagation(); copyImageUrl('${safeUrl}')">
                    <i class="fa-regular fa-copy"></i>
                </button>
                <button type="button" title="预览" aria-label="预览"
                        onclick="event.stopPropagation(); previewImage('${safeUrl}')">
                    <i class="fa-regular fa-eye"></i>
                </button>
                <button type="button" class="danger" title="删除" aria-label="删除"
                        onclick="event.stopPropagation(); deleteImage('${safeUrl}')">
                    <i class="fa-regular fa-trash-can"></i>
                </button>
            </div>
        </figure>
        `;
    }).join('');
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

    const contextMenu = document.createElement('div');
    contextMenu.id = 'image-context-menu';
    contextMenu.className = 'context-menu';
    contextMenu.setAttribute('role', 'menu');
    const menuWidth = 190;
    const left = Math.min(event.clientX, window.innerWidth - menuWidth - 12);
    const top = Math.min(event.clientY, window.innerHeight - 110);
    contextMenu.style.left = Math.max(8, left) + 'px';
    contextMenu.style.top = Math.max(8, top) + 'px';

    contextMenu.innerHTML = `
        <button type="button" role="menuitem"
                onclick="copyImageUrl('${imageUrl}'); hideContextMenu()">
            <i class="fa-regular fa-copy"></i>复制图片 URL
        </button>
        <button type="button" role="menuitem" class="danger"
                onclick="deleteImage('${imageUrl}'); hideContextMenu()">
            <i class="fa-regular fa-trash-can"></i>删除图片
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

// 重置文件选择
function resetFileSelection() {
    const fileInfo = document.getElementById('file-info');
    const fileInput = document.getElementById('image-file');
    const uploadButton = document.getElementById('upload-button');
    const uploadArea = document.getElementById('upload-area');
    if (fileInfo) fileInfo.classList.add('hidden');
    if (uploadButton) uploadButton.disabled = true;
    if (fileInput) fileInput.value = '';
    if (uploadArea) uploadArea.classList.remove('dragover');
}

// 处理文件选择
function handleFileSelect(file) {
    if (!file) {
        resetFileSelection();
        return;
    }

    // 文件类型检查
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp'];
    if (!file.type.startsWith('image/') || !allowedTypes.includes(file.type.toLowerCase())) {
        showNotification('请选择有效的图片文件（JPG、PNG、GIF、WebP）', 'error');
        resetFileSelection();
        return;
    }

    // 文件大小检查
    const maxSize = 10 * 1024 * 1024;
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
    document.getElementById('file-name').textContent = file.name;
    document.getElementById('file-size').textContent = formatFileSize(file.size);
    document.getElementById('file-info').classList.remove('hidden');

    // 检查账号选择
    const accountSelect = document.getElementById('upload-account');
    const uploadButton = document.getElementById('upload-button');
    if (uploadButton) {
        uploadButton.disabled = !(accountSelect && accountSelect.value);
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

// 图片预览功能（兼容传入 URL 字符串或图片对象）
function previewImage(image) {
    const url = (typeof image === 'string') ? image : ((image && image.url) || '');
    const name = (typeof image === 'object' && image && image.name) ? image.name : '';
    currentPreviewUrl = url;
    document.getElementById('preview-image').src = url;
    document.getElementById('preview-title').textContent = name || '图片预览';
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
            btn.classList.add('is-active');
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i><span>自动滚动</span>';
            showNotification('已启用自动滚动', 'success');
        } else {
            btn.classList.remove('is-active');
            btn.innerHTML = '<i class="fa-solid fa-pause"></i><span>暂停滚动</span>';
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
                    logContainer.innerHTML = `
            <div class="empty-state" style="padding:32px 12px;">
                <div class="empty-icon" style="background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.08);color:#64748b;"><i class="fa-regular fa-file-lines"></i></div>
                <strong style="color:#94a3b8;">暂无日志</strong>
                <p>机器人启动后将在此输出运行记录</p>
            </div>`;
                }
                updateLogStats(0, 0);
            }
        })
        .catch(error => {
            console.error('获取日志失败:', error);
            const logContainer = document.getElementById('log-container');
            if (logContainer) {
                logContainer.innerHTML = `
                    <div class="empty-state compact">
                        <div class="empty-icon" style="color:var(--danger);"><i class="fa-solid fa-triangle-exclamation"></i></div>
                        <strong>获取日志失败</strong>
                        <p>请检查服务状态或稍后重试</p>
                    </div>`;
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
        <div class="loading-row"><i class="fa-solid fa-circle-notch fa-spin"></i>加载讨论列表中…</div>
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
                    <div class="empty-state compact">
                        <div class="empty-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
                        <strong>加载失败</strong>
                        <p>${data.message || '加载讨论列表失败'}</p>
                    </div>
                `;
                checkGitHubAuth();
            }
        })
        .catch(error => {
            console.error('加载讨论列表失败:', error);
            container.innerHTML = `
                <div class="empty-state compact">
                    <div class="empty-icon"><i class="fa-solid fa-plug-circle-xmark"></i></div>
                    <strong>加载失败</strong>
                    <p>请检查网络连接后重试</p>
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
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-regular fa-comments"></i></div>
                <strong>暂无讨论</strong>
                <p>点击「新建讨论」创建第一个讨论</p>
            </div>
        `;
        return;
    }

    container.innerHTML = currentDiscussions.map(discussion => `
        <article class="discussion-item" role="button" tabindex="0"
                 onclick="showDiscussionDetail(${discussion.number})"
                 onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showDiscussionDetail(${discussion.number});}">
            <div class="list-item-head" style="margin-bottom:10px;">
                <div class="row" style="min-width:0;">
                    <img src="${discussion.user.avatar_url}" alt="${discussion.user.login}" class="discussion-avatar">
                    <div style="min-width:0;">
                        <h4 style="margin:0;font-size:14.5px;font-weight:700;color:var(--ink);word-break:break-word;">${discussion.title}</h4>
                        <p class="field-hint" style="margin:3px 0 0;">
                            <i class="fa-solid fa-user"></i> ${discussion.user.login} · ${formatDate(discussion.created_at)}
                        </p>
                    </div>
                </div>
                <div class="row-wrap">
                    <span class="badge ${discussion.state === 'open' ? 'badge-success' : 'badge-neutral'}">
                        ${discussion.state === 'open' ? '开放' : '已关闭'}
                    </span>
                    <span class="field-hint"><i class="fa-regular fa-comment"></i> ${discussion.comments_count}</span>
                </div>
            </div>

            <div class="body-preview markdown-body">${marked.parse(discussion.body || '无内容')}</div>

            ${discussion.labels && discussion.labels.length > 0 ? `
            <div class="row-wrap mt-3">
                ${discussion.labels.map(label => `<span class="badge badge-info">${label}</span>`).join('')}
            </div>
            ` : ''}
        </article>
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
        <div class="row-wrap" style="margin-bottom:14px;">
            <img src="${currentDiscussion.user.avatar_url}" alt="${currentDiscussion.user.login}" class="discussion-avatar">
            <div>
                <p style="margin:0;font-weight:600;color:var(--ink);">${currentDiscussion.user.login}</p>
                <p class="field-hint" style="margin:0;">${formatDate(currentDiscussion.created_at)}</p>
            </div>
        </div>
        <div class="markdown-body">${content}</div>
    `;

    // 更新评论列表
    const commentsContainer = document.getElementById('comments-list');
    if (currentDiscussion.comments && currentDiscussion.comments.length > 0) {
        commentsContainer.innerHTML = currentDiscussion.comments.map(comment => {
            const commentBody = marked.parse(comment.body || '');

            return `
            <article class="list-item">
                <div class="list-item-head" style="margin-bottom:6px;">
                    <div class="row">
                        <img src="${comment.user.avatar_url}" alt="${comment.user.login}" class="discussion-avatar">
                        <div>
                            <p style="margin:0;font-weight:600;color:var(--ink);font-size:13px;">${comment.user.login}</p>
                            <p class="field-hint" style="margin:0;">${formatDate(comment.created_at)}</p>
                        </div>
                    </div>
                    <button type="button"
                        data-comment-id="${comment.id}"
                        onclick="deleteComment(${currentDiscussion.number}, ${comment.id}, '${comment.user.login}')"
                        class="delete-comment-btn btn btn-sm btn-danger"
                        title="删除评论"
                        style="display:none;">
                        <i class="fa-solid fa-trash-can"></i>删除
                    </button>
                </div>
                <div class="markdown-body">${commentBody}</div>
            </article>
            `;
        }).join('');
    } else {
        commentsContainer.innerHTML = `
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-regular fa-comment-dots"></i></div>
                <strong>暂无评论</strong>
                <p>在下方发表第一条评论</p>
            </div>
        `;
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
                    document.querySelector('input[name="DedeUserID"]').value = data.data.DedeUserID || '';
                    document.querySelector('input[name="DedeUserID__ckMd5"]').value = data.data.DedeUserID__ckMd5 || '';
                    document.querySelector('input[name="sid"]').value = data.data.sid || '';
                    
                    
                    document.getElementById('qrcode-status').innerHTML = 
                        `<span class="text-success">登录成功！用户信息已自动填充</span>`;
                    
                    showNotification('扫码登录成功，用户信息已自动填充', 'success');
                } else {
                    // 根据状态码更新提示信息
                    const statusElement = document.getElementById('qrcode-status');
                    switch(data.code) {
                        case 86101:
                            statusElement.textContent = '等待扫码...';
                            break;
                        case 86090:
                            statusElement.innerHTML = '<span class="text-warning">已扫码，请在手机上确认登录</span>';
                            break;
                        case 86038:
                            statusElement.innerHTML = '<span class="text-danger">二维码已过期，请重新扫码</span>';
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
            <div class="empty-state">
                <div class="empty-icon"><i class="fa-solid fa-users"></i></div>
                <strong>还没有账号</strong>
                <p>点击右上角「添加账号」添加第一个 B 站账号</p>
                <button class="btn btn-primary" onclick="showAddAccountModal()">
                    <i class="fa-solid fa-plus"></i>添加账号
                </button>
            </div>`;
        return;
    }

    container.innerHTML = accounts.map((account, index) => {
        const keywordCount = Object.keys(account.keyword || {}).length;
        const keywordPreview = Object.entries(account.keyword || {}).slice(0, 3).map(([keyword, reply]) => `
            <div class="keyword-row">
                <div style="min-width:0;">
                    <span class="kw">${keyword}</span>
                    <div class="reply">${reply}</div>
                </div>
            </div>`).join('');

        return `
        <div class="list-item">
            <div class="list-item-head">
                <div class="list-item-title">
                    <span class="dot ${account.enabled ? 'green' : ''}"></span>
                    <h4>${account.name}</h4>
                    <span class="badge badge-info">UID ${account.config.self_uid}</span>
                    <span class="badge ${account.enabled ? 'badge-success' : 'badge-neutral'}">
                        ${account.enabled ? '已启用' : '已禁用'}
                    </span>
                </div>
                <div class="list-actions">
                    <button class="btn ${account.enabled ? 'btn-warning' : 'btn-success'} btn-sm" onclick="toggleAccount(${index})">
                        <i class="fa-solid ${account.enabled ? 'fa-pause' : 'fa-play'}"></i>${account.enabled ? '禁用' : '启用'}
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="editAccount(${index})">
                        <i class="fa-solid fa-pen"></i>编辑
                    </button>
                    <button class="btn btn-ghost btn-sm" style="color:var(--danger);" onclick="deleteAccount(${index})">
                        <i class="fa-solid fa-trash-can"></i>删除
                    </button>
                </div>
            </div>

            <div class="row-wrap mb-2">
                <span class="chip"><i class="fa-solid fa-at"></i>艾特用户 ${account.at_user ? '开启' : '关闭'}</span>
                <span class="chip"><i class="fa-solid fa-user-plus"></i>自动关注 ${account.auto_focus ? '开启' : '关闭'}</span>
                <span class="chip"><i class="fa-solid fa-key"></i>关键词 ${keywordCount} 条</span>
                ${account.auto_reply_follow ? '<span class="chip"><i class="fa-solid fa-handshake"></i>关注回复</span>' : ''}
            </div>

            ${keywordCount > 0 ? `<div class="list-item-meta" style="display:block;padding-top:10px;">
                <p class="field-hint mb-2">关键词预览</p>
                ${keywordPreview}
                ${keywordCount > 3 ? `<p class="field-hint mt-2">还有 ${keywordCount - 3} 条，请在「编辑」中查看</p>` : ''}
            </div>` : ''}
        </div>`;
    }).join('');
}

function updateGlobalKeywordsList(keywords) {
    const container = document.getElementById('global-keywords-list');
    if (!container) return;

    if (!keywords || Object.keys(keywords).length === 0) {
        container.innerHTML = `
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-solid fa-key"></i></div>
                <strong>暂无全局关键词</strong>
                <p>添加后对所有账号生效</p>
            </div>`;
        return;
    }

    container.innerHTML = Object.entries(keywords).map(([keyword, reply]) => `
        <div class="keyword-row">
            <div style="min-width:0;">
                <span class="kw">${keyword}</span>
                <div class="reply">${reply}</div>
            </div>
            <button class="icon-btn" style="color:var(--danger);flex:0 0 auto;" onclick="deleteGlobalKeyword(${JSON.stringify(keyword)})" aria-label="删除关键词">
                <i class="fa-solid fa-trash-can"></i>
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
        container.innerHTML = `
            <div class="empty-state compact">
                <div class="empty-icon"><i class="fa-solid fa-key"></i></div>
                <strong>暂无关键词</strong>
                <p>添加关键词后，命中消息将自动回复</p>
            </div>`;
        return;
    }

    // 使用数据属性存储原始数据，避免转义问题
    container.innerHTML = Object.entries(keywords).map(([keyword, reply]) => `
        <div class="keyword-row"
             data-keyword="${encodeURIComponent(keyword)}"
             data-reply="${encodeURIComponent(reply)}">
            <div style="min-width:0;">
                <span class="kw">${keyword}</span>
                <div class="reply">${reply}</div>
            </div>
            <div class="list-actions">
                <button type="button" class="icon-btn edit-keyword-btn" aria-label="编辑关键词">
                    <i class="fa-solid fa-pen"></i>
                </button>
                <button type="button" class="icon-btn is-danger delete-keyword-btn" aria-label="删除关键词">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        </div>
    `).join('');

    // 事件委托只需绑定一次
    if (container.dataset.delegated === '1') return;
    container.dataset.delegated = '1';
    container.addEventListener('click', function (e) {
        const keywordRow = e.target.closest('.keyword-row');
        if (!keywordRow) return;

        const keyword = decodeURIComponent(keywordRow.getAttribute('data-keyword') || '');
        const reply = decodeURIComponent(keywordRow.getAttribute('data-reply') || '');

        if (e.target.closest('.edit-keyword-btn')) {
            openEditKeywordModal(keyword, reply);
        } else if (e.target.closest('.delete-keyword-btn')) {
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
                statusText.className = 'stat-value is-text status-inline ' + (data.running ? 'is-on' : 'is-off');
                statusText.innerHTML = data.running
                    ? '<i class="fa-solid fa-circle"></i> 运行中'
                    : '<i class="fa-solid fa-circle"></i> 已停止';
            }

            updateTopbarStatus(!!data.running);

            const navBadge = document.getElementById('nav-accounts-badge');
            if (navBadge) {
                const count = data.total_accounts_count || 0;
                navBadge.textContent = count;
                navBadge.classList.toggle('hidden', count === 0);
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
                statusText.className = 'stat-value is-text status-inline is-unknown';
                statusText.innerHTML = '<i class="fa-solid fa-circle"></i> 获取失败';
            }
            updateTopbarStatus(null);
        });
}

// 顶栏状态胶囊
function updateTopbarStatus(running) {
    const pill = document.getElementById('topbar-status');
    if (!pill) return;
    pill.classList.toggle('is-on', running === true);
    pill.classList.toggle('is-off', running === false);
    const label = pill.querySelector('.label');
    if (label) {
        label.textContent = running === true ? '机器人运行中' : (running === false ? '机器人已停止' : '连接异常');
    }
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
            if (elementId === 'cpu-progress') circle.setAttribute('stroke', '#4f46e5');
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
                const cpu = stats.cpu || {};
                const memory = stats.memory || {};
                const disk = stats.disk || {};
                const cpuUsage = Number(cpu.usage ?? 0);
                const memUsage = Number(memory.usage ?? 0);
                const diskUsage = Number(disk.usage ?? 0);

                // 更新CPU信息
                updateProgressCircle('cpu-progress', cpuUsage);
                document.getElementById('cpu-usage').textContent = `${cpuUsage}%`;
                const physicalCores = cpu.physical_cores ?? cpu.logical_cores ?? '-';
                const logicalCores = cpu.logical_cores ?? cpu.physical_cores ?? '-';
                document.getElementById('cpu-cores').textContent =
                    `${physicalCores}物理 / ${logicalCores}逻辑`;

                // 更新内存信息
                updateProgressCircle('mem-progress', memUsage);
                document.getElementById('mem-usage').textContent = `${memUsage}%`;
                document.getElementById('mem-details').textContent =
                    `${Number(memory.used ?? 0)}/${Number(memory.total ?? 0)} GB`;

                // 更新磁盘信息
                updateProgressCircle('disk-progress', diskUsage);
                document.getElementById('disk-usage').textContent = `${diskUsage}%`;
                document.getElementById('disk-details').textContent =
                    `${Number(disk.used ?? 0)}/${Number(disk.total ?? 0)} GB`;

                // 更新系统负载 (仅Unix系统)
                const loadContainer = document.getElementById('load-average-container');
                if (loadContainer) {
                    if (Array.isArray(stats.load_avg) && stats.load_avg.length >= 3) {
                        loadContainer.style.display = 'block';
                        document.getElementById('load-1').textContent = stats.load_avg[0];
                        document.getElementById('load-5').textContent = stats.load_avg[1];
                        document.getElementById('load-15').textContent = stats.load_avg[2];
                    } else {
                        loadContainer.style.display = 'none';
                    }
                }

                updateNetworkData(stats);
            }
        })
        .catch(error => console.error('获取系统状态失败:', error));
}

// 启动机器人
// 按钮忙碌态：防止重复提交
function setButtonBusy(btn, busy) {
    if (!btn || !btn.classList || !btn.classList.contains('btn')) return;
    if (busy) {
        btn.dataset.label = btn.innerHTML;
        btn.setAttribute('aria-busy', 'true');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>处理中…';
    } else {
        btn.removeAttribute('aria-busy');
        btn.disabled = false;
        if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
}

// 内联 onclick 场景下取得触发按钮
function activeButton() {
    const ev = window.event;
    if (ev && ev.target && ev.target.closest) {
        const btn = ev.target.closest('button');
        if (btn) return btn;
    }
    return document.activeElement;
}

// 通用控制请求：统一处理忙碌态、提示与状态刷新
function runBotCommand(url, failMessage) {
    const btn = activeButton();
    setButtonBusy(btn, true);
    return fetch(url, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            showNotification(data.message, data.success ? 'success' : 'error');
            if (data.success) fetchBotStatus();
        })
        .catch(error => {
            console.error(failMessage, error);
            showNotification(failMessage + '，请检查网络连接', 'error');
        })
        .finally(() => {
            setButtonBusy(btn, false);
        });
}

// 启动机器人
function startBot() {
    return runBotCommand('/api/start_bot', '启动机器人失败');
}

// 停止机器人
function stopBot() {
    return runBotCommand('/api/stop_bot', '停止机器人失败');
}

// 重启机器人
function restartBot() {
    return runBotCommand('/api/restart_bot', '重启机器人失败');
}

// 显示通知
function showNotification(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    const icons = {
        success: 'fa-solid fa-circle-check',
        error: 'fa-solid fa-circle-exclamation',
        warning: 'fa-solid fa-triangle-exclamation',
        info: 'fa-solid fa-circle-info'
    };
    const kind = icons[type] ? type : 'info';

    toast.className = `toast ${kind}`;
    toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    toast.innerHTML = `
        <span class="toast-icon"><i class="${icons[kind]}"></i></span>
        <span class="toast-body">${message}</span>
        <button type="button" class="toast-close" aria-label="关闭通知">
            <i class="fa-solid fa-xmark"></i>
        </button>
    `;

    const close = () => {
        toast.classList.remove('is-visible');
        setTimeout(() => toast.remove(), 240);
    };
    toast.querySelector('.toast-close').addEventListener('click', close);

    (container || document.body).appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('is-visible'));

    setTimeout(close, 5000);
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
    
    // 用户名显示（由 base.html 的 data-username 提供，静态 JS 无法使用 Jinja）
    const username = document.body.dataset.username || '';
    if (username) {
        document.querySelectorAll('.username-display').forEach(el => {
            el.textContent = username;
        });
    }

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