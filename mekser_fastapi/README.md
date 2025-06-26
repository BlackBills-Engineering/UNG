# Mekser FastAPI Gateway

## Назначение

Шлюз предоставляет HTTP / JSON-интерфейс поверх протокола Mekser MKR-5 DART
(документация на протокол — см. файлы *MKR5_PROTOCOL* и *MKR5 Technical Manual*).
Используется кассовой системой или 1С для управления колонками MEKSER 2001-…2024 гг.

## Быстрый старт (Linux / macOS)

```bash

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# эмуляция пары портов
socat -d -d PTY,link=/dev/ttyV0,raw,echo=0 PTY,link=/dev/ttyV1,raw,echo=0

# запустить тестовый эмулятор колонки (пример в docs/emulator.py)
python docs/emulator.py /dev/ttyV1 1 &

# запустить API
uvicorn app.main:app --reload
```
