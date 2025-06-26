from pydantic import BaseModel, Field
from typing import Optional

class PumpStatusOut(BaseModel):
    status:        str
    nozzle:        int | None = None
    nozzle_out:    bool | None = None
    price:         float | None = Field(None, description="Цена/л")
    volume:        float | None = Field(None, description="Отпущено, л")
    amount:        float | None = Field(None, description="Сумма, валюта")
    alarm:         int   | None = Field(None, description="Код аварии (десятичный)")

class PresetIn(BaseModel):
    volume: Optional[float] = Field(None, gt=0, description="Литры")
    amount: Optional[float] = Field(None, gt=0, description="Сумма")