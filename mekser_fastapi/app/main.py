import logging
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from app.api import router as pump_router
from app.config import DEFAULT_PUMP_IDS, WS_POLL_INTERVAL
from app.core import PumpService

# Логирование
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mekser.main")
logger.info("Starting Mekser Pump API application")

app = FastAPI(
    title="Mekser Pump API",
    version="0.1.0"
)
app.include_router(pump_router)

from .ws import router as ws_router
app.include_router(ws_router)

@app.on_event("startup")
async def on_startup():
    logger.info("FastAPI startup")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("FastAPI shutdown")

@app.websocket("/ws/events")
async def pump_events(websocket: WebSocket):
    """
    WebSocket для трансляции событий колонок в реальном времени.
    По любой смене статуса (status/nozzle/nozzle_out/price/volume/amount/alarm)
    отправляет JSON {"pump_id":…, …fields…}.
    """
    await websocket.accept()
    last_states: dict[int, dict] = {}
    try:
        while True:
            for pump_id in DEFAULT_PUMP_IDS:
                data = PumpService.return_status(pump_id)
                if data and last_states.get(pump_id) != data:
                    payload = {"pump_id": pump_id, **data}
                    await websocket.send_json(payload)
                    last_states[pump_id] = data
            await asyncio.sleep(WS_POLL_INTERVAL)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
