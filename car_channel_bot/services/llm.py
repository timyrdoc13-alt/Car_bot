from __future__ import annotations

import asyncio
import hashlib
import random
import time

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
    "{fx_block}"
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
    "   Если цены нет: \"Расчётная стоимость - {missing_price_hint}\".\n"
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
    "10) Сразу после блока из п.9 одна строка с контактным призывом: {cta_tail}\n"
    "\n"
    "Требования к длине: не превышай {max_chars} символов."
)


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fx = NbrbFxService(settings)
        self._caption_cache: dict[str, tuple[float, str]] = {}
        self._system_prompt_cache: tuple[float, str] | None = None
        self._system_prompt_cache_ttl: float = 30.0

    def _cache_key_for_prompt(self, raw_text: str) -> str:
        h = hashlib.sha256()
        h.update(self._settings.llm_model.encode())
        h.update(b"\0")
        h.update(str(self._settings.llm_max_output_chars).encode())
        h.update(b"\0")
        h.update(raw_text.encode("utf-8", errors="replace"))
        return h.hexdigest()

    def _caption_cache_get(self, key: str) -> str | None:
        ttl = self._settings.caption_cache_ttl_seconds
        if ttl <= 0:
            return None
        ent = self._caption_cache.get(key)
        if not ent:
            return None
        exp, text = ent
        if time.monotonic() > exp:
            del self._caption_cache[key]
            return None
        return text

    def _caption_cache_set(self, key: str, text: str) -> None:
        ttl = self._settings.caption_cache_ttl_seconds
        if ttl <= 0:
            return
        self._caption_cache[key] = (time.monotonic() + float(ttl), text)

    async def _get_system_prompt_cached(self) -> str:
        now = time.monotonic()
        if self._system_prompt_cache is not None:
            exp, prompt = self._system_prompt_cache
            if now < exp:
                return prompt
        prompt = await self._build_system_prompt()
        self._system_prompt_cache = (now + self._system_prompt_cache_ttl, prompt)
        return prompt

    async def _build_system_prompt(self) -> str:
        if self._settings.fx_enabled:
            fx_body = await self._fx.llm_fx_block()
            fx_block = (
                "Справочно по курсам НБ РБ (только для пересчёта из цены в объявлении; не выдумывай курсы):\n"
                f"{fx_body}\n"
            )
        else:
            fx_block = ""
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

        cache_key = self._cache_key_for_prompt(raw_text)
        cached = self._caption_cache_get(cache_key)
        if cached is not None:
            log.info("llm_caption_cache_hit", key_prefix=cache_key[:16])
            return cached

        url = self._settings.llm_base_url.rstrip("/") + "/chat/completions"
        system_prompt = await self._get_system_prompt_cached()
        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
            "temperature": 0.4,
            "max_tokens": self._settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        max_attempts = self._settings.llm_max_retries + 1
        base = self._settings.llm_retry_base_seconds
        last_err: BaseException | None = None
        async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
            for attempt in range(max_attempts):
                try:
                    r = await client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError) as e:
                        log.error("llm_bad_response", data=data, attempt=attempt)
                        raise RuntimeError("LLM response malformed") from e
                    text = content.strip()
                    out = self._enforce_cap(text)
                    self._caption_cache_set(cache_key, out)
                    if attempt > 0:
                        log.info("llm_retry_success", attempt=attempt)
                    return out
                except httpx.HTTPStatusError as e:
                    last_err = e
                    code = e.response.status_code
                    if attempt >= max_attempts - 1 or code not in (429, 502, 503, 504):
                        log.warning("llm_http_error", status=code, attempt=attempt)
                        raise
                    wait = base * (2**attempt) + random.uniform(0, 0.25)
                    if code == 429:
                        ra = e.response.headers.get("Retry-After")
                        if ra is not None:
                            try:
                                wait = max(wait, float(ra))
                            except ValueError:
                                pass
                    log.warning(
                        "llm_retry_scheduled",
                        status=code,
                        attempt=attempt,
                        sleep_s=round(wait, 2),
                    )
                    await asyncio.sleep(wait)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = e
                    if attempt >= max_attempts - 1:
                        log.warning("llm_transport_error", attempt=attempt, err=str(e))
                        raise
                    wait = base * (2**attempt) + random.uniform(0, 0.25)
                    log.warning(
                        "llm_retry_scheduled_transport",
                        attempt=attempt,
                        sleep_s=round(wait, 2),
                    )
                    await asyncio.sleep(wait)
        if last_err is not None:
            raise last_err
        raise RuntimeError("LLM request failed")

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
