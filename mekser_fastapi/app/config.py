"""
Небольшой конфиг-модуль.
При необходимости параметры можно читать из переменных окружения.
"""
import logging
from pathlib import Path
from typing import Final

# -------- Serial port ----------
SERIAL_PORT: Final[str] = "/dev/ttyS0"
BAUDRATE:   Final[int] = 9600
BYTESIZE:   Final[int] = 8
PARITY:     Final[str] = "N"
STOPBITS:   Final[int] = 1
TIMEOUT:    Final[float] = 0.5             # чтение 500 мс

# -------- Pump addresses --------
# Адрес = 0x50 + pump_id (1-based).
DEFAULT_PUMP_IDS = list(range(1, 9))

# -------- Логика ----------------
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF


logger = logging.getLogger("mekser.config")
logger.debug(f"Configuring SERIAL_PORT={SERIAL_PORT}, BAUDRATE={BAUDRATE}, TIMEOUT={TIMEOUT}")
