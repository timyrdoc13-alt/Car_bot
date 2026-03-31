from __future__ import annotations

import httpx
import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.services.fx_nbrb import NbrbFxService

log = structlog.get_logger()

SYSTEM_PROMPT = (
    "Ты оформляешь объявления для Telegram-канала о подборе авто на русском языке.\n"
    "Верни ТОЛЬКО финальный текст поста, без комментариев, кавычек и пояснений.\n"
    "\n"
    "КРИТИЧЕСКОЕ ПРАВИЛО ДОСТОВЕРНОСТИ:\n"
    "- Используй ТОЛЬКО факты из входных данных пользователя.\n"
    "- НИЧЕГО не выдумывай (комплектации, опции, повреждения, историю и т.п.).\n"
    "- Если поля нет, пиши: \"уточнить у менеджера\".\n"
    "- Не добавляй URL/ссылки/http/www.\n"
    "\n"
    "ЖЕСТКИЙ ШАБЛОН (сохрани порядок блоков):\n"
    "1) Первая строка: \"{{YEAR}} {{MAKE}} {{MODEL}} {{TRIM}}\". Если части нет — подставь \"уточнить у менеджера\".\n"
    "2) Разделитель: \"----------------------------\"\n"
    "3) 8-10 строк фактов с префиксом \"⠀✅ \"\n"
    "4) Разделитель: \"----------------------------\"\n"
    "5) Тех.блок строго в 4 строках:\n"
    "   \"⠀⚙️ Привод - ...\"\n"
    "   \"⠀⚙️ КПП - ...\"\n"
    "   \"⠀⚙️ Двигатель - ...\"\n"
    "   \"⠀⚙️ Пробег - ...\"\n"
    "6) Разделитель: \"----------------------------\"\n"
    "7) Строка цены: \"Расчётная стоимость - {{USD}}💲\".\n"
    "   Если цены нет: \"Расчётная стоимость - уточнить у менеджера\".\n"
    "8) Блок доставки (всегда, без изменений смысла):\n"
    "   \"Доставка в Беларусь:\"\n"
    "   \"— Погрузка на автовоз\"\n"
    "   \"— До Минска от 7 дней\"\n"
    "   \"— Полный пакет документов\"\n"
    "   \"— Повторная растаможка не требуется, только утильсбор (660–1200 BYN)\"\n"
    "9) Финальный CTA блок (строго):\n"
    "   \"⠀📷  ДЕТАЛЬНЫЕ ФОТО\"\n"
    "   \"⠀📂  ИСТОРИЯ АВТО\"\n"
    "   \"⠀🎬  ПОДБОР АНАЛОГОВ\"\n"
    "   \"ПИШИ В ЛС, Я ПОДБЕРУ ЖЕЛАЕМЫЙ ВАРИАНТ ⬇️\"\n"
    "\n"
    "Требования к длине: не превышай {max_chars} символов."
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
        head = lines[0] if lines else "Авто уточнить у менеджера"
        raw_facts = lines[1:11] if len(lines) > 1 else []
        facts = [f"⠀✅ {f.lstrip('- ').strip()}" for f in raw_facts[:10]]
        while len(facts) < 8:
            facts.append("⠀✅ уточнить у менеджера")
        text = "\n".join(
            [
                head,
                "----------------------------",
                *facts[:10],
                "----------------------------",
                "⠀⚙️ Привод - уточнить у менеджера",
                "⠀⚙️ КПП - уточнить у менеджера",
                "⠀⚙️ Двигатель - уточнить у менеджера",
                "⠀⚙️ Пробег - уточнить у менеджера",
                "----------------------------",
                "Расчётная стоимость - уточнить у менеджера",
                "",
                "Доставка в Беларусь:",
                "— Погрузка на автовоз",
                "— До Минска от 7 дней",
                "— Полный пакет документов",
                "— Повторная растаможка не требуется, только утильсбор (660–1200 BYN)",
                "",
                "⠀📷  ДЕТАЛЬНЫЕ ФОТО",
                "⠀📂  ИСТОРИЯ АВТО",
                "⠀🎬  ПОДБОР АНАЛОГОВ",
                "",
                "ПИШИ В ЛС, Я ПОДБЕРУ ЖЕЛАЕМЫЙ ВАРИАНТ ⬇️",
            ]
        )
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
