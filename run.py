"""Yagona server: FastAPI + Mini App + aiogram bot.

Bot FastAPI `lifespan` ichida fonda ishga tushadi, shuning uchun bu skript
faqat uvicorn'ni ko'taradi. Render kabi platformalarda web service buyrug'i
sifatida ham ishlatish mumkin::

    python run.py

Muhit o'zgaruvchilari: ``WEB_HOST`` (standart ``0.0.0.0``), ``WEB_PORT``
(standart ``8000``, Render'da ``PORT`` avtomatik olinadi).
"""

from __future__ import annotations

import logging
import os

import uvicorn

from api.server import app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT") or os.getenv("PORT") or "8000")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
