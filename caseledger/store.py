"""JSONL-based storage for cases."""
import json
import os
from pathlib import Path

DEFAULT_PATH = "cases.jsonl"


def _get_path(path=None):
    return path or os.environ.get("CASELEDGER_FILE", DEFAULT_PATH)


def load_cases(path=None):
    filepath = _get_path(path)
    if not os.path.exists(filepath):
        return []
    cases = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def save_cases(cases, path=None):
    filepath = _get_path(path)
    with open(filepath, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")


def append_case(case, path=None):
    filepath = _get_path(path)
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
