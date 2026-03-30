from __future__ import annotations

import httpx
import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.services.fx_nbrb import NbrbFxService

log = structlog.get_logger()

SYSTEM_PROMPT = (
    "You format car listings for a Telegram sales channel in Russian.\n"
    "Rules:\n"
    "- Output ONLY the final post text, no preamble or quotes.\n"
    "- First line: short trim line (make/model/trim level).\n"
    "- Then 4-6 bullet lines starting with \"- \" with concrete facts "
    "(year, mileage, engine, drive, condition, etc.).\n"
    "- Use only facts present in the user message. If a fact is missing, "
    "write briefly \"уточнить у менеджера\" for that bullet instead of inventing.\n"
    "- Do NOT include URLs, links, http(s), or \"www.\" in the post text.\n"
    "\n"
    "FX and prices (mandatory when rates below are present):\n"
    "{fx_block}\n"
    "\n"
    "- One compact price line with 🇧🇾 and 🇷🇺: BYN and RUB for the same USD "
    "price from the listing; use ONLY NBRB rates above (not myfin).\n"
    "- Format example: \"🇧🇾 … BYN (экв. N $)\" and \"🇷🇺 … RUB (экв. N $)\"; round sensibly.\n"
    "- If no $ price, do not invent conversions; use \"{missing_price_hint}\".\n"
    "- Last line: short CTA — {cta_tail}\n"
    "- Keep total length under {max_chars} characters (hard limit). Be concise."
)


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fx = NbrbFxService(settings)

    async def _build_system_prompt(self) -> str:
        fx_block = await self._fx.llm_fx_block()
        return SYSTEM_PROMPT.format(
            max_chars=self._settings.llm_max_output_chars,
            fx_block=fx_block,
            missing_price_hint=self._settings.price_missing_hint,
            cta_tail=self._settings.cta_tail,
        )

    async def generate_caption(self, raw_text: str) -> str:
        if not self._settings.llm_api_key:
            log.warning("llm_no_key_fallback")
            return await self._fallback_caption(raw_text)

        url = self._settings.llm_base_url.rstrip("/") + "/chat/completions"
        system_prompt = await self._build_system_prompt()
        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
            "temperature": 0.4,
            "max_tokens": 800,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            log.error("llm_bad_response", data=data)
            raise RuntimeError("LLM response malformed") from e
        text = content.strip()
        return self._enforce_cap(text)

    def _enforce_cap(self, text: str) -> str:
        cap = min(1024, self._settings.llm_max_output_chars + 50)
        if len(text) <= cap:
            return text
        truncated = text[: cap - 1].rstrip()
        if "\n" in truncated:
            truncated = truncated[: truncated.rfind("\n")]
        return truncated + "…"

    async def _fallback_caption(self, raw: str) -> str:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        head = lines[:1] or ["Автомобиль"]
        bullets = lines[1:6] if len(lines) > 1 else ["- Подробности — у менеджера"]
        body = "\n".join(head + [ln if ln.startswith("-") else f"- {ln}" for ln in bullets])
        snap = await self._fx.get_snapshot()
        if snap is not None:
            tail = (
                f"🇧🇾 / 🇷🇺 — пересчитайте цену в $ по курсу НБ РБ на {snap.rate_date_display} "
                f"(1 USD = {snap.byn_per_usd:.4f} BYN, 1 USD ≈ {snap.rub_per_usd:.2f} RUB). "
                f"{self._settings.cta_tail}"
            )
        else:
            tail = f"🇧🇾Цена РБ — уточнить\n🇷🇺РФ — уточнить\n{self._settings.cta_tail}"
        text = f"{body}\n{tail}"
        return self._enforce_cap(text)

    @staticmethod
    def build_prompt_from_parsed_fields(fields: dict[str, str | None]) -> str:
        parts: list[str] = []
        for k, v in fields.items():
            if not v:
                continue
            s = str(v).strip()
            if s.lower().startswith(("http://", "https://", "www.")):
                continue
            parts.append(f"{k}: {s}")
        return "\n".join(parts) if parts else "Нет данных"
