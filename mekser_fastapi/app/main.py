"""
Точка запуска:
> uvicorn app.main:app --reload
"""

import logging
from fastapi import FastAPI
from .api import router as pump_router

# настройка лога
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = FastAPI(
    title="Mekser Pump API",
    description=(
        "REST-шлюз к ТРК Mekser (MKR-5, DART)\n\n"
        "/docs или /redoc"
    ),
    version="0.1.0",
)

app.include_router(pump_router)