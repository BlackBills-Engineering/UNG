"""
driver.py – слой L1+L2 DART
* собирает/разбирает кадры
* крутит CRC-16/CCITT (poly-0x1021, init-0x0000)
* thread-safe работа с pyserial
"""

from __future__ import annotations

import threading
import time
import logging
from typing import List

import serial

from .config import (
    SERIAL_PORT,
    BAUDRATE,
    BYTESIZE,
    PARITY,
    STOPBITS,
    TIMEOUT,
    CRC_INIT,
    CRC_POLY,
)
from .enums import DartTrans

_log = logging.getLogger("mekser.driver")


# ───────────────────────────────── CRC-16 CCITT ────────────────────────────
def calc_crc(data: bytes) -> int:
    crc = CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc & 0xFFFF


# ───────────────────────────────── Driver ──────────────────────────────────
class DartDriver:
    """
    Потокобезопасный драйвер одной RS-485 линии (MKR-5 DART-протокол).
    """

    STX = 0x02
    ETX = 0x03
    SF  = 0xFA        # обязательный байт “Stop Frame” по спеке!

    def __init__(self):
        self._ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=TIMEOUT,
        )
        self._lock = threading.Lock()
        self._seq = 0x00                       # чередуем 0x00 / 0x80 для CTRL.seq
        logging.getLogger("mekser.driver").info(
            f"Opening serial port {SERIAL_PORT} @ {BAUDRATE} bps"
        )

    # ────────── публичный API ──────────
    def transact(self, addr: int, trans_blocks: List[bytes], timeout: float = 1.0) -> bytes:
        """
        Отправить один кадр (STX … ETX SF) с произвольным списком транзакций
        и дождаться ответа того же адреса. Возвращает «сырые» байты кадра.
        """
        log = logging.getLogger("mekser.driver.transact")
        log.debug(
            f"transact(addr=0x{addr:02X}, blocks={len(trans_blocks)}, timeout={timeout})"
        )
        frame = self._build_frame(addr, trans_blocks)
        log.debug(f"TX frame: {frame.hex()}")

        with self._lock:
            self._ser.write(frame)
            self._ser.flush()

            start = time.time()
            buf = bytearray()
            while time.time() - start < timeout:
                chunk = self._ser.read(self._ser.in_waiting or 1)
                if chunk:
                    buf += chunk
                    if self.ETX in chunk:          # увидели ETX – почти конец
                        # дочитываем SF (1 байт) если ещё нет
                        if len(buf) < 2 or buf[-1] != self.SF:
                            buf += self._ser.read(1)
                        break
            log.debug(f"RX frame: {buf.hex()}")
            return bytes(buf)

    # ────────── приватка ──────────
    def _build_frame(self, addr: int, blocks: List[bytes]) -> bytes:
        """
        addr  – байт адреса 0x50…0x6F
        blocks – список готовых транзакций L3 (каждая с [TRANS][LNG]…)
        """        
        body = b"".join(blocks)
        lng = len(body)
        ctrl = 0xF0                      # 1111 0000 – Host, DATA
        seq = self._seq
        self._seq = 0x80 if self._seq == 0x00 else 0x00  # toggle 0x00/0x80

        hdr = bytes([addr, ctrl, seq, lng]) + body
        crc = calc_crc(hdr)     # CRC по ADR…Data

        # ============= CRC VALIDATION START ============== #
        crc_bytes = bytes([crc & 0xFF, crc >> 8])
        full_data_with_crc = hdr + crc_bytes
        validation_crc = calc_crc(full_data_with_crc)
        print(f"CRC validation: {validation_crc:04X} (should be 0000)")
        if validation_crc != 0x0000:
            print("⚠️  CRC implementation may be incorrect!")
        else:
            print("✅ CRC implementation is correct")
        # ============= CRC VALIDATION END ============== #
        
        frame = (
            bytes([self.STX])
            + hdr
            + bytes([crc & 0xFF, crc >> 8])              # CRC-L, CRC-H
            + bytes([self.ETX, self.SF])                 # ETX, SF (0xFA)
        )
        
        print(f"{'=' * 10} BUILD FRAME BEGIN {'=' * 10}\n{frame}\n{'=' * 10} BUILD FRAME END {'=' * 10}\n")
        
        return frame

    # ────────── helpers для частых команд (CD1/3/4) ──────────
    def cd1(self, pump_id: int, dcc: int) -> bytes:
        """CD1 = [0x01, 0x01, DCC]"""
        print("frame sent: ",0x50 + pump_id, [bytes([DartTrans.CD1, 0x01, dcc])])
        
        return self.transact(0x50 + pump_id, [bytes([DartTrans.CD1, 0x01, dcc])])

    def cd3_preset_volume(self, pump_id: int, value_bcd: bytes) -> bytes:
        return self.transact(
            0x50 + pump_id, [bytes([DartTrans.CD3, 0x04]) + value_bcd]
        )

    def cd4_preset_amount(self, pump_id: int, value_bcd: bytes) -> bytes:
        return self.transact(
            0x50 + pump_id, [bytes([DartTrans.CD4, 0x04]) + value_bcd]
        )
    
    def test_cmd(self) -> bytes:
        test_frame = bytes([
            0x51, 0xF0, 0x00, 0x03, 0x01, 0x01, 0x00, 0x59, 0xAD, 0x03, 0xFA, 
        ])
    
        print(f"Sending test frame: {' '.join(f'{b:02X}' for b in test_frame)}")
    
        with self._lock:
            self._ser.write(test_frame)
            self._ser.flush()
            
            # Ждем ответ
            time.sleep(0.1)
            res = self._ser.read(64)
            
            print(f"Received response: {' '.join(f'{b:02X}' for b in res)}")
            return res
        

driver = DartDriver()  # singleton