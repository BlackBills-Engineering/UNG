#!/usr/bin/env python3
import binascii
from typing import Optional, Dict

STX = 0x02     # Start of Text
ETX = 0xAD     # в реальных кадрах — байт перед SF
SF  = 0xFA     # Stop flag

def bcd_to_int(bcd_bytes: bytes) -> int:
    """Пакованный BCD → целое число."""
    result = 0
    for b in bcd_bytes:
        hi = (b >> 4) & 0xF
        lo = b & 0xF
        result = result * 100 + hi * 10 + lo
    return result

def parse_frame(hex_frame: str) -> Dict:
    raw = bytes.fromhex(hex_frame)
    # проверяем STX/SF
    if raw[0] != STX or raw[-1] != SF:
        raise ValueError("Некорректный кадр (нет STX/SF)")

    adr  = raw[1]
    ctrl = raw[2]
    # найдём позицию ETX (0xAD)
    try:
        etx_idx = raw.index(ETX)
    except ValueError:
        raise ValueError("В кадре нет ETX")

    # CRC — два байта перед ETX
    crc_low, crc_high = raw[etx_idx-2], raw[etx_idx-1]

    # транзакция начинается сразу после CTRL
    trans_code = raw[3]
    trans_len  = raw[4]
    data_bytes = raw[5:5+trans_len]

    result: Dict[str, Optional[int]] = {
        "address": adr,
        "ctrl": ctrl,
        "trans_code": trans_code,
        "raw_data": binascii.hexlify(data_bytes).decode(),
        "nozzle": None,
        "nozzle_in": None,
        "price": None,
    }

    # DC3 — Nozzle Status and Filling Price
    if trans_code == 0x03:
        # если length == 1 → только NOZIO
        if trans_len == 1:
            nozio = data_bytes[0]
            result["nozzle"]    = nozio & 0x0F
            result["nozzle_in"] = ((nozio >> 4) & 1) == 0
        # если length >= 4 → PRI(3 bytes) + NOZIO
        elif trans_len >= 4:
            price_bcd = data_bytes[0:3]
            nozio     = data_bytes[3]
            result["price"]     = bcd_to_int(price_bcd)
            result["nozzle"]    = nozio & 0x0F
            result["nozzle_in"] = ((nozio >> 4) & 1) == 0

    # DC1 — Pump Status
    elif trans_code == 0x01 and trans_len >= 1:
        status = data_bytes[0]
        result["pump_status"] = status  # 0..7 см. спецификацию

    # DC2 — Volume & Amount
    elif trans_code == 0x02 and trans_len >= 8:
        vol_bcd = data_bytes[0:4]
        amt_bcd = data_bytes[4:8]
        result["volume"] = bcd_to_int(vol_bcd)
        result["amount"] = bcd_to_int(amt_bcd)

    return result

if __name__ == "__main__":
    samples = [
        "0251f0000301",
        "0251f0000301010059ad03fa",
    ]
    for hx in samples:
        try:
            info = parse_frame(hx)
            print(f"\nFrame: {hx}")
            for k, v in info.items():
                print(f"  {k:12} = {v}")
        except Exception as e:
            print(f"\nНе удалось разобрать кадр {hx!r}: {e}")
