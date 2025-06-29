"""
core.py – слой бизнес-операций. Сюда не “просачивается” pyserial.
Возвращает словари/объекты, которыми пользуются Эндпоинты FastAPI.
"""

import threading, time, logging
from typing import Dict, Any

from app.config import TIMEOUT
from .driver import calc_crc, driver
from .enums import PumpStatus, DccCmd, DecimalConfig, DartTrans

logger = logging.getLogger("mekser.core")

STX = 0x02
ETX = 0x03
SF  = 0xFA

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

    def _parse_frame(cls, frame: bytes) -> dict:
        """
        Парсит любой принятый буфер и извлекает транзакции DC1, DC2, DC3, DC5.
        """
        try:
            stx = frame.index(driver.STX)
            etx = frame.index(driver.ETX, stx+1)
        except ValueError:
            logger.warning("No full frame in buffer")
            return {}
        raw = frame[stx+1:etx]  # ADR,CTRL,SEQ,LNG,TRANS,LEN,data...,CRC-L,CRC-H
        if len(raw) < 5:
            return {}
        lng = raw[3]
        pos = 4
        parsed = {}
        idx = 0
        while idx < lng:
            trans = raw[pos]
            dlen = raw[pos+1]
            data = raw[pos+2:pos+2+dlen]
            pos += 2 + dlen
            idx += 2 + dlen

            if trans == DartTrans.DC1 and dlen >= 1:
                code = data[0]
                parsed["status"] = PumpStatus(code).name
            elif trans == DartTrans.DC2 and dlen == 8:
                vol = bcd_to_int(data[0:4]) / (10**DecimalConfig.VOLUME.value)
                amo = bcd_to_int(data[4:8]) / (10**DecimalConfig.AMOUNT.value)
                parsed["volume"] = vol
                parsed["amount"] = amo
            elif trans == DartTrans.DC3 and dlen == 4:
                price = bcd_to_int(data[0:3]) / (10**DecimalConfig.UNIT_PRICE.value)
                nozio = data[3]
                parsed["price"] = price
                parsed["nozzle"] = nozio & 0x0F
                parsed["nozzle_out"] = bool(nozio & 0x10)
            elif trans == DartTrans.DC5 and dlen >= 1:
                parsed["alarm"] = data[0]

        return parsed

    @staticmethod
    def _parse_dc1(frame: bytes) -> dict:
        """
        Ищем и валидируем L2-фреймы в любом буфере и возвращаем {'status':int}.
        """
        logger.debug(f"_parse_dc1: raw buffer={frame.hex()}")
        buf = frame
        i = 0
        while True:
            try:
                stx = buf.index(STX, i)
            except ValueError:
                break
            end = buf.find(SF, stx+1)
            if end == -1:
                break
            raw = buf[stx:end+1]
            logger.debug(f"_parse_dc1: candidate={raw.hex()}")
            # минимальные проверки
            if len(raw) >= 9 and raw[-2] == ETX:
                lng = raw[4]
                if len(raw) >= 5 + lng + 4:
                    # CRC-0 проверка ADR…CRC-H
                    crc_region = raw[1 : 1+3+1+lng]  # ADR..last data byte
                    crc_l = raw[5+lng]
                    crc_h = raw[6+lng]
                    if calc_crc(raw[1:5+lng+1]) != 0:
                        logger.warning(f"_parse_dc1: CRC-0 failed {raw.hex()}")
                    else:
                        trans = raw[3]
                        if trans == DartTrans.DC1 and lng >= 1:
                            status = raw[5]
                            logger.info(f"_parse_dc1: parsed status={status}")
                            return {"status": status}
            i = end + 1
        logger.warning("_parse_dc1: DC1 not found")
        return {}

    # @staticmethod
    # def _parse_dc_frame(frame: bytes) -> dict:
    #     """
    #     Полностью логирующий и надёжный парсер DC1 (Pump Status) из произвольного буфера.
    #     """
    #     logger.debug(f"_parse_dc_frame: raw buffer = {frame.hex()}")

    #     # Вспомогательный класс-экстрактор
    #     class _Extractor:
    #         def __init__(self):
    #             self.buf = bytearray()
    #         def feed(self, data: bytes):
    #             self.buf += data
    #         def frames(self):
    #             out = []
    #             while True:
    #                 # ищем STX
    #                 try:
    #                     idx = self.buf.index(STX)
    #                 except ValueError:
    #                     break
    #                 # убедимся, что до STX есть ADR/CTRL (2 байта)
    #                 if idx < 2:
    #                     del self.buf[:idx+1]
    #                     continue
    #                 # ищем SF
    #                 try:
    #                     end = self.buf.index(SF, idx+1)
    #                 except ValueError:
    #                     break
    #                 raw = bytes(self.buf[idx-2:end+1])
    #                 del self.buf[:end+1]
    #                 out.append(raw)
    #             return out

        # Функция разбора 1-го DART-фрейма
        def _parse_single(raw: bytes) -> dict:
            # минимальный размер: ADR,CTRL,STX,TRANS,LNG,CRC_L,CRC_H,ETX,SF = 9 байт + data
            if len(raw) < 9 or raw[2] != STX or raw[-2] != ETX or raw[-1] != SF:
                logger.debug(f"_parse_dc_frame: invalid raw frame {raw.hex()}")
                return {}
            lng = raw[4]
            # полный размер = 5 заголовок + lng + 4 (CRC_L,CRC_H,ETX,SF)
            if len(raw) < 5 + lng + 4:
                logger.debug(f"_parse_dc_frame: incomplete frame {raw.hex()}")
                return {}
            # проверим CRC-16-CCITT
            # CRC–0 проверка: ADR…CRC-H → 0x0000
            crc_l, crc_h = raw[5+lng], raw[6+lng]
            crc_region = raw[0 : 5+lng+2]   # ADR..CRC-H
            if calc_crc(crc_region) != 0:
                logger.warning(f"_parse_dc_frame: CRC-0 failed on {raw.hex()}")
                return {}

            # crc_calc = PumpService.crc16_ccitt(raw[0:5+lng])
            # if crc_calc != ((crc_h<<8)|crc_l):
            #     logger.warning(f"_parse_dc_frame: CRC mismatch {raw.hex()}")
            #     return {}


            # tranzactionизвлечение транзации DC1
            trans = raw[3]
            if trans == DartTrans.DC1 and lng >= 1:
                status = raw[5]
                logger.info(f"_parse_dc_frame: parsed status={status}")
                return {"status": status}
            return {}

        extractor = _Extractor()
        extractor.feed(frame)
        for raw in extractor.frames():
            parsed  = _parse_single(raw)
            if parsed :
                return parsed 

        logger.warning("_parse_dc_frame: DC1 not found in buffer")
        return {}

    # ———— публичные методы ———— #
    @classmethod
    def return_status(cls, pump_id: int):
        logger.info(f"return_status: pump_id={pump_id}")
        frame = driver.cd1(pump_id, DccCmd.RETURN_STATUS)
        logger.debug(f"Raw frame received: {frame.hex()}")

        if not frame:
            logger.error("Empty frame on status")
            return {}
        parsed = cls._parse_frame(frame)
        logger.info(f"Parsed status: {parsed}")
        return parsed


    @classmethod
    def authorize(cls, pump_id: int, volume: float | None = None, amount: float | None = None)-> dict:
        # (1) при необходимости – пресет
        logger.info(f"authorize: pump_id={pump_id}, volume={volume}, amount={amount}")
        if volume is not None:
            v_int = int(volume * 10**DecimalConfig.VOLUME.value)
            driver.cd3_preset_volume(pump_id, int_to_bcd(v_int))
            time.sleep(TIMEOUT)
        if amount is not None:
            a_int = int(amount * 10**DecimalConfig.AMOUNT.value)
            driver.cd4_preset_amount(pump_id, int_to_bcd(a_int))
            time.sleep(TIMEOUT)
        # (2) AUTHORIZE
        frame = driver.cd1(pump_id, DccCmd.AUTHORIZE)
        logger.debug(f"Raw frame after AUTHORIZE: {frame.hex()}")
        parsed = cls._parse_dc1(frame)
        logger.info(f"Parsed authorize response: {parsed}")
        return parsed

    @classmethod
    def stop(cls, pump_id: int):
        frame = driver.cd1(pump_id, DccCmd.STOP)
        return cls._parse_dc1(frame)

    @classmethod
    def reset(cls, pump_id: int):
        frame = driver.cd1(pump_id, DccCmd.RESET)
        return cls._parse_dc1(frame)
    
    @classmethod
    def switch_off(cls, pump_id: int):
        frame = driver.cd1(pump_id, DccCmd.SWITCH_OFF)
        return cls._parse_dc1(frame)