from fastapi import APIRouter, Path, HTTPException
from .core import PumpService
from .schemas import PumpStatusOut, PresetIn

router = APIRouter(prefix="/pump", tags=["Pump operations"])

def _not_found_if_empty(data: dict):
    if not data:
        raise HTTPException(504, "От колонки нет ответа или кадр некорректен")
    return data

@router.get("/{pump_id}/status", response_model=PumpStatusOut)
def get_status(pump_id: int = Path(..., ge=1, description="Номер колонки (1-...)")):
    return _not_found_if_empty(PumpService.return_status(pump_id))

@router.get("/scan")
def scan_pumps(max_id: int = 4):
    found = []
    for pump_id in range(1, max_id+1):
        try:
            resp = PumpService.return_status(pump_id)
            if resp.get("status"):
                found.append({"pump_id": pump_id, **resp})
        except:
            pass
    return {"found": found}

@router.post("/{pump_id}/authorize", response_model=PumpStatusOut)
def authorize(
    pump_id: int = Path(..., ge=1),
    preset: PresetIn | None = None,
):
    if preset and preset.volume and preset.amount:
        raise HTTPException(400, "Укажите либо volume, либо amount, но не оба")
    return _not_found_if_empty(
        PumpService.authorize(pump_id, volume=preset.volume if preset else None,
                              amount=preset.amount if preset else None)
    )

@router.post("/{pump_id}/stop", response_model=PumpStatusOut)
def stop(pump_id: int = Path(..., ge=1)):
    return _not_found_if_empty(PumpService.stop(pump_id))

@router.post("/{pump_id}/reset", response_model=PumpStatusOut)
def reset(pump_id: int = Path(..., ge=1)):
    return _not_found_if_empty(PumpService.reset(pump_id))