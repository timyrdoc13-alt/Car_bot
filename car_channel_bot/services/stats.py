from car_channel_bot.db.repositories import Database


class StatsService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def summary_text(self) -> str:
        s = await self._db.stats_summary()
        return (
            f"Всего публикаций в канал: {s['posts_total']}\n"
            f"Авто-одобрено (события): {s['auto_approved']}"
        )
