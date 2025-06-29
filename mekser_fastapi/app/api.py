from asyncio import sleep
from typing import List
from app.enums import DartTrans
from fastapi import APIRouter, Path, HTTPException
from .core import PumpService
from .schemas import PumpStatusOut, PresetIn

from app.driver import driver

import logging

router = APIRouter(prefix="/pump-old", tags=["Pump operations"])


logger = logging.getLogger("mekser.api")

@router.post("/{pump_id}/price")
def update_price(pump_id: int, prices: List[float]):
    blocks = []
    for p in prices:
        sleep(1)
        amount = int(p * 100)
        s = f"{amount:06d}"
        bcd = bytes(int(s[i:i+2]) for i in (0, 2, 4))
        blocks.append(bcd)
    data = bytes([DartTrans.CD5, len(blocks)*3]) + b"".join(blocks)
    driver.transact(addr= 0x50 + pump_id, trans_blocks=[data] )
    return {"message": "price upd sent"}

def _not_found_if_empty(data: dict):
    if not data:
        raise HTTPException(504, "От колонки нет ответа или кадр некорректен")
    return data

@router.get("/{pump_id}/status", response_model=PumpStatusOut)
def get_status(pump_id: int = Path(..., ge=1, description="Номер колонки (1-...)")):
    logger.info(f"HTTP GET /pump/{pump_id}/status called")
    data = PumpService.return_status(pump_id)
    logger.info(f"GET status response: {data}")
    return _not_found_if_empty(data)

@router.get("/scan")
async def scan_pumps(max_id: int = 4):
    found = []
    for pump_id in range(1, max_id + 1):
        await sleep(1)
        try:
            resp = PumpService.return_status(pump_id)
            if resp:
                logger.info("PUMP RESP ", resp)
                found.append({"pump_id": {pump_id, resp}})
        except Exception:
            continue
    return {"found": found}


@router.post("/{pump_id}/authorize", response_model=PumpStatusOut)
def authorize(
    pump_id: int = Path(..., ge=1),
    preset: PresetIn | None = None,
):
    logger.info(f"HTTP POST /pump/{pump_id}/authorize body={preset}")
    if preset and preset.volume and preset.amount:
        raise HTTPException(400, "Укажите либо volume, либо amount, но не оба")
    data = PumpService.authorize(pump_id, volume=preset.volume if preset else None,
                              amount=preset.amount if preset else None)
    logger.info(f"POST authorize response: {data}")
    return _not_found_if_empty(data)

@router.post("/{pump_id}/stop", response_model=PumpStatusOut)
def stop(pump_id: int = Path(..., ge=1)):
    logger.info(f"HTTP POST /pump/{pump_id}/stop called")
    data = PumpService.stop(pump_id)
    logger.info(f"POST stop response: {data}")
    return _not_found_if_empty(data)

@router.post("/{pump_id}/reset", response_model=PumpStatusOut)
def reset(pump_id: int = Path(..., ge=1)):
    logger.info(f"HTTP POST /pump/{pump_id}/reset called")
    data = PumpService.reset(pump_id)
    logger.info(f"POST reset response: {data}")
    return _not_found_if_empty(data)

@router.post("/switch-off")
def reset(pump_id: int = Path(..., ge=1)):
    logger.info(f"HTTP POST /switch-off called")
    data = PumpService.switch_off(pump_id)
    logger.info(f"POST reset response: {data}")
    return _not_found_if_empty(data)