from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import structlog

from car_channel_bot.config.settings import Settings

log = structlog.get_logger()


@dataclass
class FxSnapshot:
    byn_per_usd: float
    rub_per_usd: float
    rate_date_display: str


class NbrbFxService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: tuple[float, FxSnapshot | None] | None = None

    async def get_snapshot(self) -> FxSnapshot | None:
        if not self._settings.fx_enabled:
            return None
        now = time.monotonic()
        if self._cache and (now - self._cache[0]) < self._settings.fx_cache_ttl_seconds:
            return self._cache[1]
        snap = await self._fetch()
        self._cache = (now, snap)
        return snap

    async def _fetch(self) -> FxSnapshot | None:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(self._settings.nbrb_fx_url)
                r.raise_for_status()
                rows = r.json()
        except Exception as e:
            log.warning("nbrb_fx_fetch_failed", error=str(e))
            return None
        byn_per_usd: float | None = None
        byn_per_one_rub: float | None = None
        date_str = ""
        for row in rows:
            code = str(row.get("Cur_Abbreviation", "")).upper()
            scale = int(row.get("Cur_Scale", 1))
            rate = float(row.get("Cur_OfficialRate", 0))
            if scale <= 0:
                continue
            per_unit = rate / scale
            if code == "USD":
                byn_per_usd = per_unit
                date_str = str(row.get("Date", ""))[:10]
            if code == "RUB":
                byn_per_one_rub = per_unit
        if byn_per_usd is None or byn_per_one_rub is None or byn_per_one_rub == 0:
            return None
        rub_per_usd = byn_per_usd / byn_per_one_rub
        snap = FxSnapshot(byn_per_usd=byn_per_usd, rub_per_usd=rub_per_usd, rate_date_display=date_str)
        log.info("nbrb_fx_refreshed", date=date_str)
        return snap

    async def llm_fx_block(self) -> str:
        snap = await self.get_snapshot()
        if snap is None:
            return "(курсы НБ РБ недоступны — не придумывай BYN/RUB)"
        return (
            f"Дата курсов НБ РБ: {snap.rate_date_display}\n"
            f"1 USD = {snap.byn_per_usd:.4f} BYN\n"
            f"1 USD ≈ {snap.rub_per_usd:.2f} RUB (через официальные курсы НБ РБ)\n"
            "Пересчёт: экв. BYN = USD * первая строка; экв. RUB = USD * третья величина."
        )
