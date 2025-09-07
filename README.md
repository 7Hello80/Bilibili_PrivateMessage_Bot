# 哔哩哔哩私信关键词自动回复机器人 (Bilibili PrivateMessage Bot)

## 概述

Bilibili PrivateMessage Bot (后文简称BPMB) 这是一个基于Bilibili私信API开发的私信关键词自动回复机器人

可设置多个关键词，对于没有自动回复的哔哩哔哩用户已可以实现自动回复了

如果你觉得好的话可以给我点个Stars吗？

## 参数配置

1. SESSDATA
`浏览器按下F12 -> 应用/application -> cookie -> https://message.bilibili.com -> SESSDATA`

2. bili_jct
`浏览器按下F12 -> 应用/application -> cookie -> https://message.bilibili.com -> bili_jct`

3. UID
在个人空间里面可以看到自己的UID

4. Device_id
`浏览器F12 -> 网络 -> 随便给一个人发送一条私信 -> 看到send_msg这个链接 -> 里面的w_dev_id就是我们需要的`

打开编辑index.py，划到最底部进行更改

## 使用方式

环境要求**Python3+**

1. 下载源码到本地
```bash
https://github.com/7Hello80/Bilibili_PrivateMessage_Bot
```

2. 安装所需的Python依赖
```bash
pip install requests uuid json
```

3. 启动服务
```bash
python3 index.py
```
