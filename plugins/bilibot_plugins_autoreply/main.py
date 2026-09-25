# -*- coding: utf-8 -*-
"""
增强自动回复插件
- 从 config.json 读取关键词回复规则(支持多个关键词)
- 每个用户每条规则有独立冷却时间(演示 PluginCache TTL)
- package.json 中声明 bypass_follow_check: true, 未关注用户也能收到回复
- 命令: !rules 查看规则列表
"""
import plugin_dev


class Plugin(plugin_dev.MessagePlugin):
    def __init__(self, bot_manager=None, config_manager=None, plugin_config=None):
        super().__init__(bot_manager, config_manager, plugin_config)
        self.version = "1.0.0"

        # 注册消息处理器
        self.register_message_handler(self.handle_rules)

        # 注册命令
        self.register_command('rules', self.cmd_rules, '查看自动回复规则')

    def on_load(self):
        self.logger.info(f"增强自动回复插件 {self.name} 加载成功, "
                         f"规则数: {len(self.config.get('rules', []) or [])}")

    def on_unload(self):
        self.logger.info(f"增强自动回复插件 {self.name} 卸载成功")

    def handle_rules(self, message_data):
        content = message_data.get('content', '')
        sender_uid = str(message_data.get('sender_uid', ''))

        for rule in self.config.get('rules', []) or []:
            keywords = rule.get('keyword', '')
            keyword_list = [k.strip() for k in str(keywords).split(';') if k.strip()]
            if not keyword_list:
                continue

            hit = any(k in content for k in keyword_list)
            if not hit:
                continue

            # 冷却检查: 同一用户同一规则在冷却期内不再回复
            cache_key = f"cooldown_{rule.get('keyword', '')}_{sender_uid}"
            if self.cache.get(cache_key):
                self.logger.debug(f"用户 {sender_uid} 命中规则但处于冷却期")
                return None

            reply = rule.get('reply', '')
            if not reply:
                return None

            cooldown = int(rule.get('cooldown_seconds', 60))
            self.cache.set(cache_key, 1, ttl=cooldown)

            self.logger.info(f"命中规则 [{rule.get('keyword')}] 回复用户 {sender_uid}")
            return reply

        return None

    def cmd_rules(self, message_data, args):
        rules = self.config.get('rules', []) or []
        if not rules:
            return "当前没有配置自动回复规则(在插件配置中添加 rules 列表)"
        lines = ["💬 自动回复规则:"]
        for i, rule in enumerate(rules, 1):
            lines.append(
                f"{i}. [{rule.get('keyword', '')}] -> {rule.get('reply', '')} "
                f"(冷却 {rule.get('cooldown_seconds', 60)}s)")
        return "\n".join(lines)
