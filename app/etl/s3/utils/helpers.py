# utils/helpers.py

from datetime import datetime

VALID_ANSWER_STATES = {"draft", "submitted", "locked"}


def utc_now():
    return datetime.utcnow().isoformat()


def validate_answer_state(state: str):
    if state not in VALID_ANSWER_STATES:
        raise ValueError(f"Invalid answer state: {state}")


def next_version(existing: dict) -> int:
    if existing and "version" in existing:
        return existing["version"] + 1
    return 1


def add_unique(lst, item):
    if item not in lst:
        lst.append(item)
    return lst