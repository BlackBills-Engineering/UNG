"""
core.py – слой бизнес-операций. Сюда не “просачивается” pyserial.
Возвращает словари/объекты, которыми пользуются Эндпоинты FastAPI.
"""

import threading, time, logging
from typing import Dict, Any

from .driver import calc_crc, driver
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

    # @staticmethod
    # def _parse_dc_frame(frame: bytes) -> dict:
    #     """
    #     Разбирает ответ насоса (DC-кадр) и возвращает словарь «status / volume / …».
    #     Если пришёл только ACK/NAK (1–2 байта) — отдаёт {}.
    #     """
    #     # короткий ACK / NAK → пропускаем
    #     if len(frame) < 6:          # ADR CTRL SEQ LNG CRC_L CRC_H  → 6 байт минимум
    #         return {}

    #     # --- дальше идёт «старый» парсер ---
    #     i = 4                       # позиция первого TRANS
    #     body = frame[4:-3]          # ADR CTRL SEQ LNG [body] CRC_L CRC_H ETX SF
    #     parsed: dict[str, object] = {}

    #     while i < len(body):
    #         trans = body[i]
    #         length = body[i + 1]
    #         payload = body[i + 2 : i + 2 + length]

    #         if trans == 0x01:       # DC1 – STATUS
    #             parsed["status"] = payload[1] & 0x0F
    #         elif trans == 0x02:     # DC2 – Volume/Amount
    #             vol  = int(payload[0:4].hex(), 16) / 100  # BCD → float
    #             amo  = int(payload[4:8].hex(), 16) / 100
    #             parsed.update(volume=vol, amount=amo)
    #         elif trans == 0x03:     # DC3 – Nozzle info
    #             parsed.update(nozzle=payload[0], nozzle_out=bool(payload[1] & 0x10))
    #         # добавляйте другие DC* по необходимости

    #         i += 2 + length

    #     return parsed



    @staticmethod
    def _parse_dc_frame(frame: bytes) -> dict:
        """
        Полностью логирующий и надёжный парсер DC1 (Pump Status) из произвольного буфера.
        """
        logger.debug(f"_parse_dc_frame: raw buffer = {frame.hex()}")

        # Вспомогательный класс-экстрактор
        class _Extractor:
            def __init__(self):
                self.buf = bytearray()
            def feed(self, data: bytes):
                self.buf += data
            def frames(self):
                out = []
                while True:
                    # ищем STX
                    try:
                        idx = self.buf.index(0x02)
                    except ValueError:
                        break
                    # убедимся, что до STX есть ADR/CTRL (2 байта)
                    if idx < 2:
                        del self.buf[:idx+1]
                        continue
                    # ищем SF
                    try:
                        end = self.buf.index(0xFA, idx+1)
                    except ValueError:
                        break
                    raw = bytes(self.buf[idx-2:end+1])
                    del self.buf[:end+1]
                    out.append(raw)
                return out

        # Функция разбора 1-го DART-фрейма
        def _parse_single(raw: bytes) -> dict:
            # минимальный размер: ADR,CTRL,STX,TRANS,LNG,CRC_L,CRC_H,ETX,SF = 9 байт + data
            if len(raw) < 9 or raw[2] != 0x02 or raw[-2] != 0x03 or raw[-1] != 0xFA:
                logger.debug(f"_parse_dc_frame: invalid raw frame {raw.hex()}")
                return {}
            lng = raw[4]
            # полный размер = 5 заголовок + lng + 4 (CRC_L,CRC_H,ETX,SF)
            if len(raw) < 5 + lng + 4:
                logger.debug(f"_parse_dc_frame: incomplete frame {raw.hex()}")
                return {}
            # проверим CRC-16-CCITT
            crc_l, crc_h = raw[5+lng], raw[6+lng]
            crc_calc = PumpService.crc16_ccitt(raw[0:5+lng])
            if crc_calc != ((crc_h<<8)|crc_l):
                logger.warning(f"_parse_dc_frame: CRC mismatch {raw.hex()}")
                return {}
            # tranzaction
            trans = raw[3]
            if trans == 0x01 and lng >= 1:
                status = raw[5]
                logger.info(f"_parse_dc_frame: parsed status={status}")
                return {"status": status}
            return {}

        extractor = _Extractor()
        extractor.feed(frame)
        for raw in extractor.frames():
            resp = _parse_single(raw)
            if resp:
                return resp

        logger.warning("_parse_dc_frame: DC1 not found in buffer")
        return {}


    # ———— публичные методы ———— #
    @classmethod
    def return_status(cls, pump_id: int):
        logger.info(f"return_status: pump_id={pump_id}")
        frame = driver.cd1(pump_id, DccCmd.RETURN_STATUS)
        logger.debug(f"Raw frame received: {frame.hex()}")

        parser = DC1Parser()
        parser.feed(frame)
        status = parser.extract()

        if status is None:
            logger.error("return_status: не удалось распарсить DC1")
            return {}
        return status

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
    

STX = 0x02
ETX = 0x03
SF  = 0xFA

class DC1Parser:
    """
    Парсит «грязный» буфер байт, ищет в нём DART-кадры и извлекает DC1 (Pump Status).
    Логирует каждый шаг.
    """
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        logger.debug(f"DC1Parser.feed: got {len(data)} bytes → {data.hex()}")
        self.buf += data

    def extract(self):
        """
        Ищем кадры вида:
        [STX][ADR][CTRL][SEQ][LNG][TRANS][LNG][DATA...][CRC-L][CRC-H][ETX][SF]
        и возвращаем первый найденный статус (0–7), иначе None.
        """
        # Добавим рамку: данные могут приходить «кусочками»
        ndx = 0
        while True:
            try:
                stx = self.buf.index(STX, ndx)
            except ValueError:
                break
            # ищем SF после STX
            end = self.buf.find(SF, stx+1)
            if end == -1:
                break
            raw = self.buf[stx : end+1]
            logger.debug(f"DC1Parser: candidate raw frame: {raw.hex()}")

            # проверяем минимум по длине и окончаниям
            if len(raw) >= 9 and raw[-2] == ETX:
                # вытаскиваем длину тела
                # структура raw: [STX, ADR, CTRL, SEQ, LNG, body..., CRC-L, CRC-H, ETX, SF]
                lng = raw[4]
                full_len = 1 + 1 + 1 + 1 + 1 + lng + 2 + 1 + 1  # STX,ADR,CTRL,SEQ,LNG,body,CRC,ETX,SF
                if len(raw) >= full_len:
                    frame = raw[:full_len]
                    # проверим CRC
                    hdr = frame[1 : 1+1+1+1+1+lng]  # ADR..последний байт body
                    crc_l, crc_h = frame[1+1+1+1+1+lng], frame[1+1+1+1+1+lng+1]
                    calc = calc_crc(hdr)
                    got = (crc_h<<8) | crc_l
                    if calc == got:
                        # транзакции внутри body
                        # первая транзакция начинается на offset=5 (STX+ADR+CTRL+SEQ+LNG)
                        off = 5
                        while off < 5 + lng:
                            trans = frame[off]
                            length = frame[off+1]
                            data = frame[off+2 : off+2+length]
                            logger.debug(f"DC1Parser: trans=0x{trans:02X} len={length} data={data.hex()}")
                            if trans == DartTrans.DC1 and length >= 1:
                                status = data[0]
                                logger.info(f"DC1Parser: parsed pump status = {status}")
                                return status
                            off += 2 + length
                    else:
                        logger.warning(f"DC1Parser: CRC mismatch {raw.hex()} (calc={calc:04X} got={got:04X})")
                else:
                    logger.debug(f"DC1Parser: frame too short ({len(raw)} < {full_len})")
            else:
                logger.debug(f"DC1Parser: invalid frame header/footer {raw.hex()}")
            # сдвигаем start
            ndx = end + 1

        logger.warning("DC1Parser: no DC1 found in buffer")
        return None