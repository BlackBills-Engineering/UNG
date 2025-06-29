import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
from app.config import DEFAULT_PUMP_IDS
from app.core import PumpService
from app.enums import PumpStatus

router = APIRouter()

@router.websocket("/ws/status")
async def websocket_pump_status(ws: WebSocket):
    """
    Клиент должен сразу после подключения прислать JSON:
      {"pump_ids": [0,1,2]}
    А потом каждые 1 сек Сервер будет шлать:
      {"type":"statuses", "data":[{"pump_id":0,"status":"RESET"},…]}
    """
    await ws.accept()
    try:
        msg = await ws.receive_json()
        pump_ids: List[int] = msg.get("pump_ids", DEFAULT_PUMP_IDS)
        while True:
            out = []
            for pid in pump_ids:
                d = PumpService.return_status(pid)
                st = d.get("status")
                out.append({
                    "pump_id": pid,
                    "status": PumpStatus(st).name if st is not None else None
                })
            await ws.send_json({"type": "statuses", "data": out})
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        # клиент отключился
        return
    except Exception:
        await ws.close()
