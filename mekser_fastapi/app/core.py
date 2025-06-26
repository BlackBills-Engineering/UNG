"""
core.py – слой бизнес-операций. Сюда не “просачивается” pyserial.
Возвращает словари/объекты, которыми пользуются Эндпоинты FastAPI.
"""

import threading, time, logging
from typing import Dict, Any

from .driver import driver
from .enums import PumpStatus, DccCmd, DecimalConfig, DartTrans

logger = logging.getLogger("mekser.core")

# ———— общие утилиты пакета ———— #
def bcd_to_int(b: bytes) -> int:
    res = 0
    for byte in b:
        res = res * 100 + ((byte >> 4) & 0xF) * 10 + (byte & 0xF)
    return res

def int_to_bcd(n: int, width: int = 4) -> bytes:
    s = str(n).rjust(width * 2, "0")
    return bytes(int(s[i:i+2]) for i in range(0, len(s), 2))

# ———— PumpService ———— #
class PumpService:

    @staticmethod
    def _parse_dc_frame(frame: bytes) -> Dict[str, Any]:
        """
        Принимает полный кадр (STX..ETX), возвращает расшифрованные данные высокого уровня.
        Проверок CRC и адреса не делаем (уже на уровне драйвера).
        """
        logger.debug(f"Parsing DC frame: {frame.hex()}")
        res: Dict[str, Any] = {}
        # body: байты между LENGTH и CRC
        if len(frame) < 8:
            return res
        body = frame[5:-3]
        i = 0
        while i < len(body):
            trans = body[i]
            length = body[i+1]
            data   = body[i+2 : i+2+length]
            i     += 2 + length
            logger.debug(f"Transaction {trans:#02x}, length={length}, data={data.hex()}")
            if trans == DartTrans.DC1:
                status_code = data[0]
                res["status"] = PumpStatus(status_code).name if status_code in PumpStatus.__members__.values() else status_code
            elif trans == DartTrans.DC2:
                res["volume"] = bcd_to_int(data[0:4]) / 10**DecimalConfig.VOLUME.value
                res["amount"] = bcd_to_int(data[4:8]) / 10**DecimalConfig.AMOUNT.value
            elif trans == DartTrans.DC3:
                res["price"]      = bcd_to_int(data[0:3]) / 10**DecimalConfig.UNIT_PRICE.value
                nozzle_info       = data[3]
                res["nozzle"]     = nozzle_info & 0x0F
                res["nozzle_out"] = bool((nozzle_info >> 4) & 0x01)
            elif trans == DartTrans.DC5:
                res["alarm"] = data[0]
                
        logger.debug(f"Resulting dict: {res}")
        return res

    # ———— публичные методы ———— #
    @classmethod
    def return_status(cls, pump_id: int):
        logger.info(f"return_status: pump_id={pump_id}")
        frame = driver.cd1(pump_id, DccCmd.RETURN_STATUS)
        logger.debug(f"Raw frame received: {frame.hex()}")
        parsed = cls._parse_dc_frame(frame)
        logger.info(f"Parsed status: {parsed}")
        return parsed

    @classmethod
    def authorize(cls, pump_id: int, volume: float | None = None, amount: float | None = None):
        # (1) при необходимости – пресет
        logger.info(f"authorize: pump_id={pump_id}, volume={volume}, amount={amount}")
        if volume is not None:
            v_int = int(volume * 10**DecimalConfig.VOLUME.value)
            driver.cd3_preset_volume(pump_id, int_to_bcd(v_int))
            time.sleep(0.05)
        if amount is not None:
            a_int = int(amount * 10**DecimalConfig.AMOUNT.value)
            driver.cd4_preset_amount(pump_id, int_to_bcd(a_int))
            time.sleep(0.05)
        # (2) AUTHORIZE
        frame = driver.cd1(pump_id, DccCmd.AUTHORIZE)
        logger.debug(f"Raw frame after AUTHORIZE: {frame.hex()}")
        parsed = cls._parse_dc_frame(frame)
        logger.info(f"Parsed authorize response: {parsed}")
        return parsed

    @classmethod
    def stop(cls, pump_id: int):
        frame = driver.cd1(pump_id, DccCmd.STOP)
        return cls._parse_dc_frame(frame)

    @classmethod
    def reset(cls, pump_id: int):
        frame = driver.cd1(pump_id, DccCmd.RESET)
        return cls._parse_dc_frame(frame)