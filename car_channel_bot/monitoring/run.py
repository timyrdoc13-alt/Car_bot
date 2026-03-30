"""Запуск: uvicorn car_channel_bot.monitoring.app:app --host 127.0.0.1 --port 8765"""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "car_channel_bot.monitoring.app:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
