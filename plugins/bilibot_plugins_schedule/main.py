# -*- coding: utf-8 -*-
"""
定时任务插件
- 按 config.json 中的任务列表定时发送消息
- 命令: !tasks 查看任务列表
- API: /tasks 任务列表
- 演示 PluginScheduler 的正确用法(on_unload 中 stop_all)
"""
import plugin_dev


class Plugin(plugin_dev.EventPlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"
        self.tasks = []

        # 注册事件: 机器人启动时打印任务数
        self.register_event_handler('bot_start', self.on_bot_start)

        # 注册命令
        self.register_command('tasks', self.cmd_tasks, '查看定时任务列表')

        # 注册 API 路由
        self.register_api_route('/tasks', self.api_tasks)

    def on_load(self):
        self.logger.info(f"定时任务插件 {self.name} 加载成功")
        self._start_tasks()

    def on_unload(self):
        # 必须停止定时线程, 否则卸载后任务仍在后台运行
        self.scheduler.stop_all()
        self.logger.info(f"定时任务插件 {self.name} 卸载成功, 已停止全部任务")

    def _start_tasks(self):
        """按配置启动定时任务"""
        self.scheduler.stop_all()  # 防止重复加载时残留
        self.tasks = []
        config_tasks = self.config.get('tasks', []) or []
        for task in config_tasks:
            name = task.get('name', '未命名任务')
            interval_minutes = int(task.get('interval_minutes', 60))
            message = task.get('message', '')
            receiver_id = int(task.get('receiver_id', 0))

            if interval_minutes <= 0 or not message or not receiver_id:
                self.logger.warning(f"任务配置无效, 已跳过: {name}")
                continue

            def make_worker(task_name, task_message, task_receiver):
                def worker():
                    ok = self.send_message(task_receiver, task_message)
                    self.logger.info(
                        f"定时任务 [{task_name}] 发送{'成功' if ok else '失败'} -> {task_receiver}")
                return worker

            self.scheduler.schedule_interval(
                interval_minutes * 60, make_worker(name, message, receiver_id))
            self.tasks.append({
                'name': name,
                'interval_minutes': interval_minutes,
                'message': message,
                'receiver_id': receiver_id
            })
            self.logger.info(f"已注册定时任务: {name} (每 {interval_minutes} 分钟)")

    def on_bot_start(self, data):
        self.logger.info(f"机器人已启动, 当前 {len(self.tasks)} 个定时任务运行中")

    def cmd_tasks(self, message_data, args):
        if not self.tasks:
            return "当前没有定时任务(在插件配置中添加 tasks 列表)"
        lines = ["📅 定时任务列表:"]
        for i, task in enumerate(self.tasks, 1):
            lines.append(
                f"{i}. {task['name']} - 每 {task['interval_minutes']} 分钟 -> {task['receiver_id']}")
        return "\n".join(lines)

    def api_tasks(self, data):
        return {'success': True, 'tasks': self.tasks}
