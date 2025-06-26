from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, WebSocket, HTTPException, Path, status
from pydantic import BaseModel, Field

from .core import PumpService                 # существующая бизнес-логика
from .driver import driver                    # протокольный драйвер
from .enums import DccCmd                     # перечисление команд CD1
from .config import DEFAULT_PUMP_IDS          # список «из коробки»

class _PumpServiceExt(PumpService):
    """Mixin с командами CD2, CD14, CD15 + WebSocket-стримом DC2."""

    @classmethod
    def allow_nozzles(cls, pump_id: int, nozzles: List[int]):
        if not nozzles or any(not (1 <= n <= 15) for n in nozzles):
            raise ValueError("nozzle numbers must be 1…15")
        block = bytes([0x02, len(nozzles), *nozzles])  # TRANS=0x02, LNG, NOZ1…n
        driver.transact(0x50 + pump_id, [block])       # 0x50..0x6F – адреса насосов
        return cls.return_status(pump_id)

    @classmethod
    def suspend(cls, pump_id: int, nozzle: int = 0):
        block = bytes([0x0E, 0x01, nozzle & 0x0F])     # TRANS=0x0E, LNG=1, NOZ
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)

    @classmethod
    def resume(cls, pump_id: int, nozzle: int = 0):
        block = bytes([0x0F, 0x01, nozzle & 0x0F])     # TRANS=0x0F, LNG=1, NOZ
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)

    @classmethod
    async def stream_filling(
        cls,
        pump_id: int,
        ws: WebSocket,
        interval: float = 0.4,
    ):
        await ws.accept()
        try:
            while True:
                frame = driver.cd1(pump_id, DccCmd.RETURN_FILL_INFO)
                data  = cls._parse_dc_frame(frame)
                if data and {"volume", "amount"} <= data.keys():
                    await ws.send_json({"v": data["volume"], "a": data["amount"]})
                await asyncio.sleep(interval)
        except Exception as exc:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
        finally:
            if not ws.client_state.name.endswith("CLOSED"):
                await ws.close()


class NozzlesIn(BaseModel):
    nozzles: List[int] = Field(..., description="Список логических сопел 1–15")

class NozzleIn(BaseModel):
    nozzle: Optional[int] = Field(
        0, ge=0, le=15, description="Сопло (0 = вся колонка)"
    )

router = APIRouter(prefix="/pump", tags=["Pump extended ops"])
@router.get("/pumps")
def list_pumps():
    items = []
    for pid in DEFAULT_PUMP_IDS:
        try:
            items.append({"pump_id": pid, **_PumpServiceExt.return_status(pid)})
        except Exception:
            items.append({"pump_id": pid, "status": "no_answer"})
    return {"items": items}

# — разрешить сопла (CD2) ————————————————————————————————————————————
@router.post("/{pump_id}/allow")
def allow_nozzles(
    pump_id: int = Path(..., ge=1),
    body: NozzlesIn = ...,
):
    try:
        return _PumpServiceExt.allow_nozzles(pump_id, body.nozzles)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

# — пауза (CD14) ————————————————————————————————————————————————
@router.post("/{pump_id}/suspend")
def suspend(
    pump_id: int = Path(..., ge=1),
    body: NozzleIn = NozzleIn(),
):
    return _PumpServiceExt.suspend(pump_id, body.nozzle or 0)

# — продолжить (CD15) ———————————————————————————————————————————
@router.post("/{pump_id}/resume")
def resume(
    pump_id: int = Path(..., ge=1),
    body: NozzleIn = NozzleIn(),
):
    return _PumpServiceExt.resume(pump_id, body.nozzle or 0)

# — WebSocket-стрим литраж/сумма ——————————————————————————————
@router.websocket("/{pump_id}/stream")
async def stream(pump_id: int, ws: WebSocket):
    await _PumpServiceExt.stream_filling(pump_id, ws)
