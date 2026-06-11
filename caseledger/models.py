"""Case model and state machine logic."""
from datetime import datetime, date

VALID_TRANSITIONS = {
    "open": ["doing"],
    "doing": ["blocked", "resolved"],
    "blocked": ["closed"],
    "resolved": ["closed"],
    "closed": [],
}

ALL_STATUSES = list(VALID_TRANSITIONS.keys())


def normalize_code(code):
    return code.replace(" ", "").upper()


def validate_transition(current_status, new_status):
    allowed = VALID_TRANSITIONS.get(current_status, [])
    return new_status in allowed


def is_overdue(case):
    if case["status"] == "closed":
        return False
    due = case.get("due_date")
    if not due:
        return False
    try:
        due_date = datetime.strptime(due, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return date.today() > due_date


def sort_key(case):
    priority = case.get("priority", 999)
    due = case.get("due_date") or "9999-12-31"
    code = case.get("code", "")
    return (priority, due, code)
