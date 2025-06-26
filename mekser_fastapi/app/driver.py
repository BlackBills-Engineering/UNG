"""
driver.py – слой L1+L2 DART:
* собирает/разбирает кадры
* крутит CRC-16/CCITT (0x1021)
* чтение/запись через pyserial с thread-safe Lock
"""

from __future__ import annotations

import threading, time, logging
from typing import List, Tuple, Dict

import serial

from .config import (
    SERIAL_PORT, BAUDRATE, BYTESIZE, PARITY, STOPBITS, TIMEOUT,
    CRC_INIT, CRC_POLY,
)
from .enums import DartTrans

_log = logging.getLogger("mekser.driver")

# ————————————————— CRC-16 ———————————————————— #
def calc_crc(data: bytes) -> int:
    crc = CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


# ————————————————— Driver class —————————————— #
class DartDriver:
    """
    Потокобезопасный драйвер одной RS-485 линии.
    """
    STX = 0x02
    ETX = 0x03

    def __init__(self):
        self._ser = serial.Serial(
            port     = SERIAL_PORT,
            baudrate = BAUDRATE,
            bytesize = BYTESIZE,
            parity   = PARITY,
            stopbits = STOPBITS,
            timeout  = TIMEOUT,
        )
        self._lock = threading.Lock()
        self._seq  = 0x00              # чередуем 0x00 / 0x80
        logger = logging.getLogger("mekser.driver")
        logger.info(f"Opening serial port {SERIAL_PORT} @ {BAUDRATE}bps")

    # ——— общий API ——— #
    def transact(self, addr: int, trans_blocks: List[bytes], timeout: float = 1.0) -> bytes:
        """
        Отправляет один кадр с arbitrary набором транзакций,
        ждёт ответ любого устройства с тем же адресом.
        Возвращает сырые байты кадра или b''.
        """
        logger = logging.getLogger("mekser.driver.transact")
        logger.debug(f"Requested transact(addr=0x{addr:02X}, blocks={len(trans_blocks)}, timeout={timeout})")
        frame = self._build_frame(addr, trans_blocks)
        logger.debug(f"Built frame: {frame.hex()}")

        with self._lock:
            logger.debug("Acquired serial lock, writing frame")
            self._ser.write(frame)
            self._ser.flush()
            logger.debug("Frame written, entering read loop")

            start = time.time()
            buf = bytearray()
            while time.time() - start < timeout:
                chunk = self._ser.read(self._ser.in_waiting or 1)
                if chunk:
                    logger.debug(f"Read chunk: {chunk.hex()}")
                    buf += chunk
                    if self.ETX in chunk:  # грубый маркер конца
                        logger.debug("Detected ETX in chunk, breaking read")
                        break
            return bytes(buf)

    # ——— утилиты ——— #
    def _build_frame(self, addr: int, blocks: List[bytes]) -> bytes:
        """
        addr — байт адреса 0x50-0x6F,
        blocks — список готовых транзакций уровня 3 (каждая уже со своим [TRANS][LNG]…)
        """
        logger = logging.getLogger("mekser.driver._build_frame")
        body = b"".join(blocks)
        lng = len(body)
        ctrl = 0xF0          # Host→Pump, data
        seq  = self._seq
        self._seq = 0x80 if self._seq == 0x00 else 0x00

        hdr_wo_crc = bytes([addr, ctrl, seq, lng]) + body
        crc = calc_crc(hdr_wo_crc)
        frame = bytes([self.STX]) + hdr_wo_crc + bytes([crc & 0xFF, crc >> 8, self.ETX])
        logger.debug(f"Header without CRC: {hdr_wo_crc.hex()}")
        logger.debug(f"CRC calculated: 0x{crc:04X}")
        logger.debug(f"Final frame: {frame.hex()}")
        return frame

    # ——— helpers для CD-команд ——— #
    def cd1(self, pump_id: int, dcc: int) -> bytes:
        """CD1 = [0x01, 0x01, DCC]"""
        addr_byte = 0x50 + pump_id
        return self.transact(
            addr_byte,
            [bytes([DartTrans.CD1, 0x01, dcc])]
        )

    def cd3_preset_volume(self, pump_id: int, value_bcd: bytes) -> bytes:
        addr_byte = 0x50 + pump_id
        return self.transact(
            addr_byte,
            [bytes([DartTrans.CD3, 0x04]) + value_bcd]
        )

    def cd4_preset_amount(self, pump_id: int, value_bcd: bytes) -> bytes:
        addr_byte = 0x50 + pump_id
        return self.transact(
            addr_byte,
            [bytes([DartTrans.CD4, 0x04]) + value_bcd]
        )

driver = DartDriver()  # singleton