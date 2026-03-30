"""FastAPI: страница мониторинга и POST /api/mashina/probe (нужен .env с токеном бота и т.д.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from car_channel_bot.config.settings import get_settings
from car_channel_bot.parsers.fields import PRICE_USD
from car_channel_bot.parsers.mashina import MashinaListingSource

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Mashina scrape monitor", version="0.1.0")


def _check_monitor_access(request: Request, x_mashina_monitor_token: Optional[str]) -> None:
    settings = get_settings()
    secret = (settings.mashina_monitor_token or "").strip()
    got = (x_mashina_monitor_token or "").strip()
    if secret:
        if got != secret:
            raise HTTPException(
                status_code=401,
                detail="Нужен заголовок X-Mashina-Monitor-Token (см. MASHINA_MONITOR_TOKEN в .env)",
            )
        return
    client_host = request.client.host if request.client else ""
    allowed = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
    if client_host not in allowed:
        raise HTTPException(
            status_code=403,
            detail="Снаружи задайте MASHINA_MONITOR_TOKEN и передайте его в X-Mashina-Monitor-Token",
        )


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC / "index.html")


class ProbeIn(BaseModel):
    region: Optional[str] = Field(default=None, description="Например all или код региона")
    model: Optional[str] = None
    brand: Optional[str] = None
    year_min: int = 0
    price_max: int = 0
    limit: int = Field(default=5, ge=1, le=30)
    list_url: Optional[str] = None
    fetch_detail: bool = False
    mashina_use_iphone_ua: bool = False
    mashina_scroll_max_rounds: Optional[int] = Field(default=None, ge=1, le=40)
    car_condition_multiple: Optional[str] = Field(
        default=None,
        description="Как в URL: 1,2 (б/у + …); опционально",
    )


@app.post("/api/mashina/probe")
async def mashina_probe(
    request: Request,
    body: ProbeIn,
    x_mashina_monitor_token: Optional[str] = Header(default=None, alias="X-Mashina-Monitor-Token"),
) -> Any:
    _check_monitor_access(request, x_mashina_monitor_token)

    trace: list[dict] = []
    filters: dict = {
        "limit": body.limit,
        "year_min": body.year_min,
        "price_max": body.price_max,
        "_trace": trace,
        "mashina_use_iphone_ua": body.mashina_use_iphone_ua,
    }
    if body.region is not None:
        filters["region"] = body.region
    if body.model is not None:
        filters["model"] = body.model
    if body.brand is not None:
        filters["brand"] = body.brand
    if body.list_url:
        filters["list_url"] = body.list_url
    if body.mashina_scroll_max_rounds is not None:
        filters["mashina_scroll_max_rounds"] = body.mashina_scroll_max_rounds
    if body.car_condition_multiple and body.car_condition_multiple.strip():
        filters["mashina_car_condition_multiple"] = body.car_condition_multiple.strip()

    settings = get_settings()
    src = MashinaListingSource(settings)
    try:
        refs = await src.search(filters)
    except Exception as e:
        trace.append(
            {
                "step": "fatal_search",
                "expected": "search без исключения",
                "got": str(e),
                "ok": False,
            }
        )
        return JSONResponse(
            status_code=200,
            content={"ok": False, "trace": trace, "refs": [], "refs_count": 0, "detail": None, "error": str(e)},
        )

    detail_payload = None
    if body.fetch_detail and refs:
        try:
            d = await src.fetch_detail(refs[0])
            detail_payload = {
                "url": d.url,
                "title": d.title,
                "price_usd": d.fields.get(PRICE_USD),
                "image_count": len(d.image_urls),
            }
        except Exception as e:
            trace.append(
                {
                    "step": "fatal_detail",
                    "expected": "fetch_detail без исключения",
                    "got": str(e),
                    "ok": False,
                }
            )

    return {
        "ok": True,
        "trace": trace,
        "refs": [{"url": r.url} for r in refs],
        "refs_count": len(refs),
        "detail": detail_payload,
    }
