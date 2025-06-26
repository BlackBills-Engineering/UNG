"""
Заготовленные константы и enum-ы.
Сделаны строго по документации MKR5 / DART.
"""

from enum import IntEnum, Enum

class PumpStatus(IntEnum):
    NOT_PROGRAMMED   = 0
    RESET            = 1
    AUTHORIZED       = 2      # + SUSPENDED = 3 (в MKR5 отсутствует)
    FILLING          = 4
    FILLING_COMPLETE = 5
    PRESET_REACHED   = 6
    SWITCHED_OFF     = 7
    SUSPENDED        = 8      # используется редко

class DccCmd(IntEnum):
    RETURN_STATUS      = 0x00
    RETURN_PUMP_PARAMS = 0x02
    RETURN_IDENTITY    = 0x03
    RETURN_FILL_INFO   = 0x04
    RESET              = 0x05
    AUTHORIZE          = 0x06
    STOP               = 0x08
    SWITCH_OFF         = 0x0A

class DartTrans(IntEnum):
    # Level-3 transaction identifiers
    CD1 = 0x01  # Command-to-pump
    CD3 = 0x03  # Preset Volume
    CD4 = 0x04  # Preset Amount
    CD5 = 0x05  # Price update

    DC1 = 0x01  # Pump Status
    DC2 = 0x02  # Volume/Amount
    DC3 = 0x03  # Nozzle status & price
    DC5 = 0x05  # Alarm

class DecimalConfig(Enum):
    """Сколько десятичных знаков примем для объёма/суммы/цены."""
    VOLUME  = 2
    AMOUNT  = 2
    UNIT_PRICE = 2