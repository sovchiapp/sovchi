import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

UZT = timezone(timedelta(hours=5))

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "absences.json"


def _load() -> dict:
    if not DATA_FILE.exists():
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_current_month_key() -> str:
    return datetime.now(UZT).strftime("%Y-%m")


def mark_absence(user_id: int, absence_type: str) -> None:
    """absence_type is either 'plan_missed' or 'report_missed'"""
    data = _load()
    month_key = get_current_month_key()
    user_key = str(user_id)

    if month_key not in data:
        data[month_key] = {}

    if user_key not in data[month_key]:
        data[month_key][user_key] = {"plan_missed": 0, "report_missed": 0}

    data[month_key][user_key][absence_type] += 1
    _save(data)


def get_absences(user_id: int, month_key: str = None) -> dict:
    data = _load()
    month_key = month_key or get_current_month_key()
    user_key = str(user_id)

    return data.get(month_key, {}).get(user_key, {"plan_missed": 0, "report_missed": 0})