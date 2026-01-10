<div align="center">

# 🤖 哔哩哔哩私信关键词自动回复机器人

### Bilibili PrivateMessage Bot (BPMB)

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/7Hello80/Bilibili_PrivateMessage_Bot?style=social)](https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/stargazers)
[![Forks](https://img.shields.io/github/forks/7Hello80/Bilibili_PrivateMessage_Bot?style=social)](https://github.com/7Hello80/Bilibili_PrivateMessage_Bot/network/members)

一款功能强大的 Bilibili 私信自动回复机器人，支持关键词自动回复、多账号管理、插件系统等功能

[功能特性](#-功能特性) • [快速开始](#-快速开始) • [配置说明](#-配置说明) • [插件开发](#-插件开发) • [常见问题](#-常见问题)

</div>

---

## 📖 目录

- [项目简介](#-项目简介)
- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [配置说明](#-配置说明)
- [插件开发](#-插件开发)
- [常见问题](#-常见问题)
- [支持项目](#-支持项目)

---

## 🎯 项目简介

Bilibili PrivateMessage Bot (BPMB) 是一个基于 Bilibili 私信 API 开发的智能私信关键词自动回复机器人。它可以帮助你：

- 🎯 **智能回复**：根据关键词自动回复私信，支持多条规则配置
- 👥 **多账号管理**：支持同时管理多个 Bilibili 账号
- 🔌 **插件系统**：支持自定义插件扩展功能
- 🖼️ **图片支持**：支持发送图片消息和图库管理

---

## 📱 Android App

除了 Web 控制面板，我们还提供了 Android 客户端应用，让你可以在手机上便捷地管理 Bilibili 私信机器人。

### 应用信息

- **应用名称**: BilibiliBotApp
- **包名**: com.bilibili.bot
- **版本**: 1.0
- **最低系统要求**: Android 7.0 (API 24) 或更高版本
- **目标系统**: Android 14 (API 34)

### 技术栈

- **开发语言**: Kotlin
- **UI 框架**: Jetpack Compose (Material 3)
- **网络请求**: Ktor Client
- **数据存储**: DataStore Preferences
- **图片加载**: Coil
- **架构组件**: ViewModel, Navigation

### 主要功能

- 📲 移动端管理机器人账号
- 🔄 实时查看私信回复记录
- ⚙️ 配置关键词回复规则
- 📊 监控机器人运行状态
- 🔔 接收消息通知

## ✨ 功能特性

| 功能 | 描述 | 状态 |
|------|------|------|
| 🔑 关键词自动回复 | 支持多条关键词规则，精确匹配回复 | ✅ 已实现 |
| @用户昵称 | 自动在回复中艾特对方 | ✅ 已实现 |
| 🔄 自动回关 | 自动关注已关注你的用户 | ✅ 已实现 |
| 👥 账号多开 | 同时管理多个 Bilibili 账号 | ✅ 已实现 |
| 📱 扫码登录 | 支持二维码扫码登录 | ✅ 已实现 |
| 🖼️ 图片消息 | 支持发送图片和图库管理 | ✅ 已实现 |
| 💬 关注自动回复 | 用户关注后自动发送欢迎消息 | ✅ 已实现 |
| 🔌 插件系统 | 支持自定义插件扩展 | ✅ 已实现 |
| 📊 系统监控 | 实时监控系统资源使用情况 | ✅ 已实现 |
| 📝 日志管理 | 完整的运行日志记录和查看 | ✅ 已实现 |

---

## 🚀 快速开始

### 环境要求

- Python 3.12 或更高版本
- pip (Python 包管理器)
- 现代浏览器 (Chrome/Firefox/Edge 等)

### 安装步骤

#### 1️⃣ 克隆项目

```bash
git clone https://github.com/7Hello80/Bilibili_PrivateMessage_Bot
cd Bilibili_PrivateMessage_Bot
```

#### 2️⃣ 安装依赖

```bash
pip install -r requirements.txt
```

#### 3️⃣ 启动服务

```bash
# Linux/Mac
python3 web_panel.py

# Windows
python web_panel.py
```

#### 4️⃣ 访问控制面板

打开浏览器访问：**http://localhost:5000**

默认登录账号：
- 用户名：`admin`
- 密码：`admin123`

⚠️ **重要提示**：首次登录后请立即修改默认密码！

---

## ⚙️ 配置说明

### 方式一：手动配置

在浏览器中打开哔哩哔哩按 `F12` 打开开发者工具，按以下步骤获取配置信息：

#### 获取 SESSDATA

```
开发者工具 -> 应用 (Application) -> Cookie -> https://message.bilibili.com -> SESSDATA
```

#### 获取 bili_jct

```
开发者工具 -> 应用 (Application) -> Cookie -> https://message.bilibili.com -> bili_jct
```

#### 获取 UID

在 Bilibili 个人空间页面地址栏中可以看到你的 UID

#### Device_id

系统会自动生成，无需手动配置

### 方式二：扫码登录 (推荐)

从 V1.0.6 版本开始支持扫码登录：

1. 打开 Web 控制面板
2. 进入账号管理页面
3. 点击"扫码登录"按钮
4. 使用 Bilibili App 扫描二维码
5. 完成登录授权

---

## 🔌 插件开发

### 插件功能使用方法

#### 创建插件

1. 在 Web 页面插件商店中创建新插件
2. 使用 VS Code 进行开发
3. 插件存放目录：`项目文件夹/plugins/bilibot_plugins_Name`

#### 插件结构

```
bilibot_plugins_插件名称/
├── main.py          # 插件入口文件
├── package.json     # 插件信息配置
└── plugin_dev.py    # 开发辅助模块
```

#### 发布插件

1. 访问 GitHub 并登录
2. 创建新仓库，名称格式：`bilibot_plugins_名称`
3. 将插件代码同步到仓库
4. `main.py` 为入口文件
5. `package.json` 为插件信息文件

#### 开发参考

- 插件商店提供 demo 示例插件供参考
- `plugin_dev.py` 提供便捷开发函数
- 欢迎各位积极提交插件，丰富插件生态

---

## ❓ 常见问题

<details>
<summary><b>Q: 如何修改默认管理员密码？</b></summary>

登录 Web 面板后，进入"账号设置"页面，可以修改管理员账号和密码。
</details>

<details>
<summary><b>Q: 支持哪些 Bilibili 账号类型？</b></summary>

支持所有类型的 Bilibili 账号，包括普通用户、UP 主等。
</details>

<details>
<summary><b>Q: 机器人会被封号吗？</b></summary>

本项目仅提供关键词自动回复功能，不涉及任何违规操作。但建议：
- 设置合理的回复频率
- 避免发送垃圾信息
- 遵守 Bilibili 用户协议
</details>

<details>
<summary><b>Q: 如何备份配置数据？</b></summary>

配置文件位于项目根目录的 `config.json`，定期备份此文件即可。
</details>

<details>
<summary><b>Q: 支持 Docker 部署吗？</b></summary>

目前暂不提供 Docker 镜像，但你可以自行编写 Dockerfile 进行部署。
</details>

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出新功能建议！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源协议。

---

## 💖 支持项目

如果这个项目对你有帮助，请考虑支持一下：

<div align="center">

### 请我喝杯咖啡 ☕

| 微信支付 | 支付宝 |
|:--------:|:------:|
| <img src="./image/vx.png" alt="微信" width="240" height="315"> | <img src="./image/alipay.jpg" alt="支付宝" width="240" height="315"> |

</div>

或者给项目点个 ⭐ Star，你的支持是我继续开发的动力！

---

<div align="center">

**如果喜欢这个项目，别忘了点个 Star ⭐**

Made with ❤️ by [7Hello80](https://github.com/7Hello80)

</div>
