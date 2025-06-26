"""
Точка запуска:
> uvicorn app.main:app --reload
"""

import logging
from fastapi import FastAPI
from .api import router as pump_router

# настройка лога
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("mekser.main")

logger.info("Starting Mekser Pump API application")


app = FastAPI(
    title="Mekser Pump API",
    description=(
        "REST-шлюз к ТРК Mekser (MKR-5, DART)\n\n"
        "/docs или /redoc"
    ),
    version="0.1.0",
)



app.include_router(pump_router)
logger.debug("Included pump_router in FastAPI app")


@app.on_event("startup")
async def on_startup():
    logger.info("FastAPI startup event fired")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("FastAPI shutdown event fired")