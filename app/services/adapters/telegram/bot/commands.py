from __future__ import annotations


class TelegramBotCommandMixin:
    async def _command_reply(self, text: str, chat_id: int | str) -> str:
        from app.services.subscription import (
            delete_subscription,
            delete_subscription_by_title,
            deliver_resource,
            list_subscriptions,
            retry_failed_resources,
        )

        command, args = self._parse_bot_command(text)
        command = command.split("@", 1)[0].lower()
        if command in ("/start", "/help", "help", "帮助"):
            return (
                "可用命令：\n"
                "/list 或 订阅列表\n"
                "订阅 名称：同时搜索剧集和电影，选择海报后订阅\n"
                "订阅剧集 剧名：只搜索剧集订阅\n"
                "订阅电影 片名：搜索电影订阅\n"
                "搜 片名：选择 TMDB 结果后搜索磁力源，返回前五个磁力链接\n"
                "重试失败\n"
                "取消订阅 名称/ID\n"
                "/id 查看当前 Chat ID"
            )
        if command in ("/id", "id"):
            return f"当前 Chat ID：{chat_id}"
        if command in ("/list", "list", "订阅列表", "列表"):
            return self._subscription_list_reply(list_subscriptions())
        if command in ("重试失败", "/retry_failed", "retry_failed"):
            result = await retry_failed_resources(20, deliver_resource)
            return f"已重试 {result.get('retried', 0)} 个，成功 {result.get('delivered', 0)} 个，失败 {result.get('failed', 0)} 个。"
        if command in ("搜", "/magnet", "magnet", "磁力搜索"):
            if not args:
                return "请输入要搜索磁力的剧名或片名，例如：搜 斗罗大陆"
            await self._send_magnet_search_choices(chat_id, args)
            return ""
        if command in ("订阅剧集",):
            if not args:
                return "请输入要订阅的剧名，例如：订阅 斗罗大陆"
            await self._send_subscription_choices(chat_id, args, "tv")
            return ""
        if command in ("/search", "/subscribe", "search", "subscribe", "订阅", "搜索"):
            if not args:
                return "请输入要订阅的名称，例如：订阅 斗罗大陆"
            await self._send_subscription_choices(chat_id, args, "multi")
            return ""
        if command in ("订阅电影", "/subscribe_movie", "subscribe_movie"):
            if not args:
                return "请输入要订阅的电影名，例如：订阅电影 流浪地球"
            await self._send_subscription_choices(chat_id, args, "movie")
            return ""
        if command in ("/cancel", "cancel", "取消订阅", "取消"):
            if not args:
                return "请输入订阅名称或 ID，例如：取消订阅 斗罗大陆"
            first = args.split()[0]
            if first.isdigit():
                delete_subscription(int(first))
                return "已取消订阅。"
            deleted = delete_subscription_by_title(args)
            return f"已取消 {deleted} 个订阅。" if deleted else "没有找到匹配的订阅。"
        return "未知命令。发送 /help 查看可用命令。"

    def _subscription_list_reply(self, subscriptions: list[dict]) -> str:
        if not subscriptions:
            return "暂无订阅。"
        lines = ["订阅列表："]
        for item in subscriptions[:30]:
            status = "完成" if item.get("status") == "completed" else item.get("status", "")
            if item.get("media_type") == "tv":
                count = int(item.get("emby_count") or 0)
                total = int(item.get("tmdb_total_count") or 0)
                progress = f"{count}/{total}集" if total else f"{count}集"
                status = f"完成 {progress}" if item.get("status") == "completed" else progress
            media_label = "剧集" if item["media_type"] == "tv" else "电影"
            lines.append(f"{item['id']}. {item['title']} ({media_label} {status})")
        return "\n".join(lines)

    def _parse_bot_command(self, text: str) -> tuple[str, str]:
        text = text.strip()
        for prefix in ("取消订阅", "订阅电影", "订阅剧集", "磁力搜索", "订阅", "搜索", "取消", "重试失败", "搜"):
            if text == prefix:
                return prefix, ""
            if text.startswith(prefix):
                return prefix, text[len(prefix):].strip()
        command, *rest = text.split(maxsplit=1)
        return command, rest[0].strip() if rest else ""
