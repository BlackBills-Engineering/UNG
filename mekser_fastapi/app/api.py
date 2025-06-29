from typing import List
import asyncio
import logging
from fastapi import APIRouter, Path, HTTPException
from app.config import DEFAULT_PUMP_IDS, TIMEOUT
from app.core import PumpService
from app.schemas import PumpStatusOut, PresetIn
from app.driver import driver
from app.enums import DartTrans, PumpStatus

router = APIRouter(prefix="/pump", tags=["Pump operations"])
logger = logging.getLogger("mekser.api")

def _not_found(data: dict):
    if not data:
        raise HTTPException(status_code=504, detail="No response or invalid frame")
    return data

@router.get("/statuses", response_model=List[PumpStatusOut])
def get_all_statuses():
    """
    Обойти все колонки из DEFAULT_PUMP_IDS и вернуть список
    {"pump_id": int, "status": str}.
    """
    results = []
    for pump_id in DEFAULT_PUMP_IDS:
        data = PumpService.return_status(pump_id)
        # если вернулся пустой dict – подчёркиваем отсутствие ответа
        status_str = data.get("status")
        results.append({
            "pump_id": pump_id,
            "status": PumpStatus(status_str).name if status_str is not None else None
        })
    return results

@router.get("/{pump_id}/status", response_model=PumpStatusOut,
            summary="Get pump status",
            description="Запрос статуса колонки (DC1 → DC1).")
def get_status(pump_id: int = Path(..., ge=1, le=len(DEFAULT_PUMP_IDS),
                                 description="Номер колонки (1…)")):
    data = PumpService.return_status(pump_id)
    return _not_found(data)

@router.post("/{pump_id}/price", summary="Update pump prices",
             description="Установка списка цен (CD5 → DC3 при запросе).")
def update_price(pump_id: int, prices: List[float]):
    blocks = []
    for p in prices:
        amount = int(p * 100)                                  # 2 десятичных
        s = f"{amount:06d}"
        bcd = bytes(int(s[i:i+2]) for i in (0,2,4))
        blocks.append(bcd)
        asyncio.sleep(TIMEOUT)
    data = bytes([DartTrans.CD5, len(blocks)*3]) + b"".join(blocks)
    driver.transact(addr=0x50 + pump_id, trans_blocks=[data])
    return {"message": "Price update sent"}

@router.post("/{pump_id}/authorize", response_model=PumpStatusOut,
             summary="Authorize pump",
             description="CD1 (AUTHORIZE), опциональный пресет объёма/суммы.")
def authorize(pump_id: int = Path(..., ge=1),
              preset: PresetIn | None = None):
    if preset and preset.volume and preset.amount:
        raise HTTPException(400, "Укажите либо volume, либо amount")
    data = PumpService.authorize(pump_id,
                                 volume=preset.volume if preset else None,
                                 amount=preset.amount if preset else None)
    return _not_found(data)

@router.post("/{pump_id}/stop", response_model=PumpStatusOut,
             summary="Stop pump",
             description="CD1 (STOP).")
def stop(pump_id: int = Path(..., ge=1)):
    data = PumpService.stop(pump_id)
    return _not_found(data)

@router.post("/{pump_id}/reset", response_model=PumpStatusOut,
             summary="Reset pump",
             description="CD1 (RESET).")
def reset(pump_id: int = Path(..., ge=1)):
    data = PumpService.reset(pump_id)
    return _not_found(data)

@router.post("/{pump_id}/switch-off", response_model=PumpStatusOut,
             summary="Switch off pump",
             description="CD1 (SWITCH_OFF).")
def switch_off(pump_id: int = Path(..., ge=1)):
    data = PumpService.switch_off(pump_id)
    return _not_found(data)
