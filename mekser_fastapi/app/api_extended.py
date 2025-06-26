# api_extended.py
# ────────────────────────────────────────────────────────────────────────────
# Дополнительные REST- и WS-ручки для MKR-5:
#   • /price        – CD5 Price Update
#   • /allow        – CD2 Allowed Nozzles
#   • /suspend      – CD14 Suspend
#   • /resume       – CD15 Resume
#   • /stream       – WebSocket: объём, сумма и событие «пистолет вынут»
#   • /pumps        – список всех колонок со статусом
# ────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, WebSocket, HTTPException, Path, status
from pydantic import BaseModel, Field, PositiveFloat, conlist

from .core import PumpService                  # бизнес-логика CD↔DC
from .driver import driver                     # формирует кадры, I/O
from .enums import DccCmd                      # константы CD1
from .config import DEFAULT_PUMP_IDS           # колонки «из коробки»

# ────────────────────────────────────────────────────────────────────────────
#  Вспомогалки
# ────────────────────────────────────────────────────────────────────────────
def _price_to_bcd(price: float) -> bytes:
    """52.50 ₽ → b'\\x05\\x25\\x00' (3 байта BCD, копейки ×100)."""
    value = int(round(price * 100))
    digits = f"{value:06d}"
    return bytes(((int(digits[i]) << 4) | int(digits[i + 1])) for i in range(0, 6, 2))

# ────────────────────────────────────────────────────────────────────────────
#  Расширенный сервис
# ────────────────────────────────────────────────────────────────────────────
class _PumpServiceExt(PumpService):
    """CD2, CD5, CD14, CD15 + WebSocket-стрим DC2/DC3."""

    # --- CD2 Allowed Nozzles ------------------------------------------------
    @classmethod
    def allow_nozzles(cls, pump_id: int, nozzles: List[int]):
        if not nozzles or any(not (1 <= n <= 16) for n in nozzles):
            raise ValueError("nozzle numbers must be 1…16")
        block = bytes([0x02, len(nozzles), *nozzles])
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)

    # --- CD5 Price Update ---------------------------------------------------
    @classmethod
    def update_price(cls, pump_id: int, price_map: dict[int, float]):
        if any(not (1 <= n <= 16) for n in price_map):
            raise ValueError("nozzle numbers must be 1…16")

        payload = bytearray()
        for nz in range(1, 17):                       # всегда 16 позиций
            payload += _price_to_bcd(price_map.get(nz, 0.0))

        block = bytes([0x05, len(payload)]) + payload
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)             # должен стать RESET

    # --- CD14 Suspend -------------------------------------------------------
    @classmethod
    def suspend(cls, pump_id: int, nozzle: int = 0):
        block = bytes([0x0E, 0x01, nozzle & 0x0F])
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)

    # --- CD15 Resume --------------------------------------------------------
    @classmethod
    def resume(cls, pump_id: int, nozzle: int = 0):
        block = bytes([0x0F, 0x01, nozzle & 0x0F])
        driver.transact(0x50 + pump_id, [block])
        return cls.return_status(pump_id)

    # --- WebSocket-стрим DC2/DC3 -------------------------------------------
    @classmethod
    async def stream_filling(cls, pump_id: int, ws: WebSocket, interval: float = 0.4):
        await ws.accept()
        last_nozzle_out = False
        try:
            while True:
                frame = driver.cd1(pump_id, DccCmd.RETURN_FILL_INFO)
                data = cls._parse_dc_frame(frame) or {}
                payload: dict[str, object] = {}

                if {"volume", "amount"} <= data.keys():
                    payload.update(v=data["volume"], a=data["amount"])

                # событие «пистолет вынут/вставлен»
                if "nozzle_out" in data:
                    nozzle_out = bool(data["nozzle_out"])
                    if nozzle_out != last_nozzle_out:
                        payload.update(event="nozzle_out" if nozzle_out else "nozzle_in",
                                       nozzle=data.get("nozzle"))
                        last_nozzle_out = nozzle_out

                if payload:
                    await ws.send_json(payload)

                await asyncio.sleep(interval)
        except Exception as exc:
            await ws.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
        finally:
            if not ws.client_state.name.endswith("CLOSED"):
                await ws.close()

# ────────────────────────────────────────────────────────────────────────────
#  Pydantic-схемы
# ────────────────────────────────────────────────────────────────────────────
class NozzlesIn(BaseModel):
    nozzles: List[int] = Field(..., description="Список сопел 1-16")

class NozzleIn(BaseModel):
    nozzle: Optional[int] = Field(0, ge=0, le=16, description="0 = вся колонка")

class PriceItem(BaseModel):
    nozzle: int = Field(..., ge=1, le=16)
    price:  PositiveFloat

class PricesIn(BaseModel):
    prices: conlist(PriceItem, min_items=1)

# ────────────────────────────────────────────────────────────────────────────
#  FastAPI-роутер
# ────────────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/pump", tags=["Pump extended ops"])

# --- список колонок ---------------------------------------------------------
@router.get("/pumps")
def list_pumps():
    items = []
    for pid in DEFAULT_PUMP_IDS:
        try:
            items.append({"pump_id": pid, **_PumpServiceExt.return_status(pid)})
        except Exception:
            items.append({"pump_id": pid, "status": "no_answer"})
    return {"items": items}

# --- CD5 Price Update -------------------------------------------------------
@router.post("/{pump_id}/price")
def set_price(pump_id: int = Path(..., ge=1), body: PricesIn = ...):
    price_map = {it.nozzle: it.price for it in body.prices}
    try:
        return _PumpServiceExt.update_price(pump_id, price_map)
    except ValueError as ve:
        raise HTTPException(400, str(ve))

# --- CD2 Allowed Nozzles ----------------------------------------------------
@router.post("/{pump_id}/allow")
def allow_nozzles(pump_id: int = Path(..., ge=1), body: NozzlesIn = ...):
    try:
        return _PumpServiceExt.allow_nozzles(pump_id, body.nozzles)
    except ValueError as ve:
        raise HTTPException(400, str(ve))

# --- CD14 Suspend -----------------------------------------------------------
@router.post("/{pump_id}/suspend")
def suspend(pump_id: int = Path(..., ge=1), body: NozzleIn = NozzleIn()):
    return _PumpServiceExt.suspend(pump_id, body.nozzle or 0)

# --- CD15 Resume ------------------------------------------------------------
@router.post("/{pump_id}/resume")
def resume(pump_id: int = Path(..., ge=1), body: NozzleIn = NozzleIn()):
    return _PumpServiceExt.resume(pump_id, body.nozzle or 0)

# --- WebSocket --------------------------------------------------------------
@router.websocket("/{pump_id}/stream")
async def stream(pump_id: int, ws: WebSocket):
    await _PumpServiceExt.stream_filling(pump_id, ws)
