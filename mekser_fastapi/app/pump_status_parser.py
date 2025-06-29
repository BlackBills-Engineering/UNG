#!/usr/bin/env python3
"""
pump_status_only.py

Простой скрипт для получения только статуса насоса (DC1) по протоколу MKR5/DART через USB→RS485.
Не запрашивает данные по пистолету и цене.

Последовательность:
1) Открытие порта с автодирекшн RS-485
2) Отправка команды Return Status (CD1, DCC=0x00)
3) Чтение и парсинг единственной транзакции DC1
4) Вывод кода статуса насоса

Настройки:
  PORT      = "COM3"
  BAUDRATE  = 9600
  PARITY    = serial.PARITY_ODD
  TIMEOUT   = 0.5
  PUMP_ADDR = 0x51
  MAX_TRIES = 10
"""

import serial
from serial.rs485 import RS485Settings
import logging
import binascii
import time

# === Параметры ===
PORT      = "COM3"
BAUDRATE  = 9600
PARITY    = serial.PARITY_ODD
TIMEOUT   = 0.5
PUMP_ADDR = 0x51
MAX_TRIES = 10

# Протокольные константы
STX, ETX, SF = 0x02, 0x03, 0xFA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def crc16_ccitt(data: bytes) -> int:
    """CRC-16-CCITT (poly=0x1021), init=0x0000."""
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


def build_frame(addr: int, trans: int, payload: bytes, tx: int) -> bytes:
    """
    Собирает DART-фрейм уровня 3:
    [ADR][CTRL][STX][TRANS][LNG][...payload...][CRC-L][CRC-H][ETX][SF]
    CTRL = 0x80 | tx (master->slave)
    """
    ctrl = 0x80 | (tx & 0x0F)
    hdr = bytes([addr, ctrl, STX, trans, len(payload)]) + payload
    crc = crc16_ccitt(hdr)
    return hdr + bytes([crc & 0xFF, (crc >> 8) & 0xFF, ETX, SF])


class FrameExtractor:
    """Выделяет полные DART-фреймы из потока байт."""
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf += data

    def get_frames(self):
        frames = []
        while True:
            try:
                idx = self.buf.index(STX)
            except ValueError:
                self.buf.clear()
                break
            if idx < 2:
                del self.buf[:idx+1]
                continue
            try:
                end = self.buf.index(SF, idx)
            except ValueError:
                break
            start = idx - 2
            raw = bytes(self.buf[start:end+1])
            del self.buf[:end+1]
            frames.append(raw)
        return frames


def parse_frame(raw: bytes):
    """
    Парсит один DART-фрейм:
    raw[0]=ADR, raw[1]=CTRL, raw[2]=STX, raw[3]=TRANS, raw[4]=LNG,
    raw[5:5+LNG]=DATA, raw[5+LNG]=CRC-L, raw[6+LNG]=CRC-H, raw[7+LNG]=ETX, raw[8+LNG]=SF
    """
    if len(raw) < 9 or raw[2] != STX or raw[-2] != ETX or raw[-1] != SF:
        return None
    length = raw[4]
    crc_l, crc_h = raw[5 + length], raw[6 + length]
    calc = crc16_ccitt(raw[:5 + length])
    if calc != ((crc_h << 8) | crc_l):
        logging.warning("CRC mismatch: got=%04X expected=%04X %s",
                        (crc_h<<8|crc_l), calc, binascii.hexlify(raw))
        return None
    return {"addr": raw[0], "trans": raw[3], "data": raw[5:5 + length]}


def get_pump_status():
    ser = serial.Serial(PORT, BAUDRATE,
                        bytesize=serial.EIGHTBITS,
                        parity=PARITY,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=TIMEOUT)
    ser.rs485_mode = RS485Settings(True, False, None, None)
    extractor = FrameExtractor()

    # 1) Return Status (CD1, DCC=0x00)
    cmd = build_frame(PUMP_ADDR, trans=0x01, payload=b'\x00', tx=1)
    logging.info("Send Return Status → %s", binascii.hexlify(cmd).decode())
    ser.reset_input_buffer()
    ser.write(cmd)

    status = None
    tries = 0

    while tries < MAX_TRIES and status is None:
        chunk = ser.read_all()
        tries += 1
        if chunk:
            extractor.feed(chunk)
            for raw in extractor.get_frames():
                info = parse_frame(raw)
                if info and info["addr"] == PUMP_ADDR and info["trans"] == 0x01:
                    if info["data"]:
                        status = info["data"][0]
                        logging.info("Pump status=%d", status)
        time.sleep(0.1)

    ser.close()
    return status


if __name__ == "__main__":
    st = get_pump_status()
    if st is None:
        print("Не удалось получить статус насоса")
    else:
        print(f"Pump status: {st}")
