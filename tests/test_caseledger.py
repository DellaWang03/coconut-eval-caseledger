"""Unit tests for caseledger."""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caseledger.models import normalize_code, validate_transition, is_overdue, sort_key
from caseledger.store import load_cases, save_cases, append_case
from caseledger.cli import main


def _run_cli(argv):
    """Run main() with captured stdout/stderr, returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with patch("sys.argv", argv), redirect_stdout(out), redirect_stderr(err):
        try:
            main()
        except SystemExit as e:
            code = e.code if e.code else 0
    return code, out.getvalue(), err.getvalue()


class TestNormalizeCode(unittest.TestCase):
    def test_strips_spaces_and_uppercases(self):
        self.assertEqual(normalize_code("ab c 123"), "ABC123")

    def test_already_normalized(self):
        self.assertEqual(normalize_code("CASE001"), "CASE001")

    def test_mixed_spaces(self):
        self.assertEqual(normalize_code("  h e l l o  "), "HELLO")

    def test_no_change_needed(self):
        self.assertEqual(normalize_code("X"), "X")


class TestDuplicateCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)

    def test_duplicate_code_rejected(self):
        args = [
            "caseledger",
            "--file", self.filepath,
            "add",
            "--code", "CASE001",
            "--title", "First",
            "--team", "dev",
            "--priority", "1",
            "--due-date", "2026-12-01",
        ]
        code, _, _ = _run_cli(args)
        self.assertEqual(code, 0)

        args2 = [
            "caseledger",
            "--file", self.filepath,
            "add",
            "--code", "case 001",
            "--title", "Duplicate",
            "--team", "dev",
            "--priority", "2",
            "--due-date", "2026-12-01",
        ]
        code2, _, err = _run_cli(args2)
        self.assertEqual(code2, 1)
        self.assertIn("duplicate", err.lower())


class TestStateTransitions(unittest.TestCase):
    def test_valid_transitions(self):
        self.assertTrue(validate_transition("open", "doing"))
        self.assertTrue(validate_transition("doing", "blocked"))
        self.assertTrue(validate_transition("doing", "resolved"))
        self.assertTrue(validate_transition("blocked", "closed"))
        self.assertTrue(validate_transition("resolved", "closed"))

    def test_invalid_transitions(self):
        self.assertFalse(validate_transition("open", "closed"))
        self.assertFalse(validate_transition("open", "blocked"))
        self.assertFalse(validate_transition("open", "resolved"))
        self.assertFalse(validate_transition("doing", "open"))
        self.assertFalse(validate_transition("doing", "closed"))
        self.assertFalse(validate_transition("blocked", "doing"))
        self.assertFalse(validate_transition("resolved", "doing"))
        self.assertFalse(validate_transition("closed", "open"))

    def test_invalid_transition_via_cli(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.close()
        try:
            args = [
                "caseledger", "--file", tmp.name,
                "add", "--code", "T001", "--title", "Test",
                "--team", "ops", "--priority", "1", "--due-date", "2026-12-01",
            ]
            code, _, _ = _run_cli(args)
            self.assertEqual(code, 0)

            args2 = [
                "caseledger", "--file", tmp.name,
                "update", "--code", "T001", "--status", "closed",
            ]
            code2, _, err = _run_cli(args2)
            self.assertEqual(code2, 1)
            self.assertIn("cannot transition", err)
        finally:
            os.unlink(tmp.name)


class TestFilterAndSort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name
        cases = [
            {
                "code": "A001", "title": "Alpha task", "team": "dev",
                "priority": 3, "due_date": "2026-06-15", "note": "",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [{"status": "open", "ts": "2026-01-01T00:00:00"}],
            },
            {
                "code": "B002", "title": "Beta task", "team": "ops",
                "priority": 1, "due_date": "2026-06-10", "note": "urgent",
                "status": "doing", "created_at": "2026-01-02T00:00:00",
                "history": [{"status": "open", "ts": "2026-01-02T00:00:00"}],
            },
            {
                "code": "C003", "title": "Charlie task", "team": "dev",
                "priority": 2, "due_date": "2026-06-20", "note": "",
                "status": "open", "created_at": "2026-01-03T00:00:00",
                "history": [{"status": "open", "ts": "2026-01-03T00:00:00"}],
            },
        ]
        save_cases(cases, self.filepath)

    def tearDown(self):
        os.unlink(self.filepath)

    def test_filter_by_team(self):
        from caseledger.cli import _filter_cases
        cases = load_cases(self.filepath)
        result = _filter_cases(cases, team="dev")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(c["team"] == "dev" for c in result))

    def test_filter_by_status(self):
        from caseledger.cli import _filter_cases
        cases = load_cases(self.filepath)
        result = _filter_cases(cases, status="doing")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "B002")

    def test_filter_by_q(self):
        from caseledger.cli import _filter_cases
        cases = load_cases(self.filepath)
        result = _filter_cases(cases, q="urgent")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["code"], "B002")

    def test_sort_by_priority_then_due_then_code(self):
        cases = load_cases(self.filepath)
        cases.sort(key=sort_key)
        codes = [c["code"] for c in cases]
        self.assertEqual(codes, ["B002", "C003", "A001"])


class TestReportOverdue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)

    def test_overdue_counts_unclosed_past_due(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        cases = [
            {
                "code": "OD1", "title": "Overdue open", "team": "dev",
                "priority": 1, "due_date": yesterday, "note": "",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
            {
                "code": "OD2", "title": "Not overdue", "team": "dev",
                "priority": 2, "due_date": tomorrow, "note": "",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
            {
                "code": "OD3", "title": "Closed past due", "team": "dev",
                "priority": 1, "due_date": yesterday, "note": "",
                "status": "closed", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
        ]
        save_cases(cases, self.filepath)

        self.assertTrue(is_overdue(cases[0]))
        self.assertFalse(is_overdue(cases[1]))
        self.assertFalse(is_overdue(cases[2]))

    def test_no_due_date_not_overdue(self):
        case = {
            "code": "X", "title": "No due", "team": "t",
            "priority": 1, "due_date": None, "note": "",
            "status": "open", "created_at": "2026-01-01T00:00:00",
            "history": [],
        }
        self.assertFalse(is_overdue(case))


class TestExportCSV(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)
        if os.path.exists(self.filepath + ".csv"):
            os.unlink(self.filepath + ".csv")

    def test_csv_headers(self):
        cases = [
            {
                "code": "CSV1", "title": "Test", "team": "dev",
                "priority": 1, "due_date": "2026-12-01", "note": "n",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
        ]
        save_cases(cases, self.filepath)
        out_csv = self.filepath + ".csv"
        args = [
            "caseledger", "--file", self.filepath,
            "export-csv", "--output", out_csv,
        ]
        _run_cli(args)
        with open(out_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
        self.assertEqual(
            headers, ["code", "title", "team", "priority", "due_date", "status", "note"]
        )

    def test_csv_empty_data(self):
        save_cases([], self.filepath)
        out_csv = self.filepath + ".csv"
        args = [
            "caseledger", "--file", self.filepath,
            "export-csv", "--output", out_csv,
        ]
        _run_cli(args)
        with open(out_csv, "r", encoding="utf-8") as f:
            content = f.read()
        lines = [l for l in content.strip().split("\n") if l]
        self.assertEqual(len(lines), 1)  # header only


class TestUpdateHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)

    def test_history_appended_on_update(self):
        args = [
            "caseledger", "--file", self.filepath,
            "add", "--code", "H001", "--title", "History test",
            "--team", "dev", "--priority", "1", "--due-date", "2026-12-01",
        ]
        _run_cli(args)

        args2 = [
            "caseledger", "--file", self.filepath,
            "update", "--code", "H001", "--status", "doing",
        ]
        _run_cli(args2)

        cases = load_cases(self.filepath)
        self.assertEqual(len(cases[0]["history"]), 2)
        self.assertEqual(cases[0]["history"][0]["status"], "open")
        self.assertEqual(cases[0]["history"][1]["status"], "doing")


if __name__ == "__main__":
    unittest.main()


class TestAddValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)

    def test_invalid_date_format(self):
        args = [
            "caseledger", "--file", self.filepath,
            "add", "--code", "X1", "--title", "Bad date",
            "--team", "dev", "--priority", "1", "--due-date", "12-01-2026",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("not a valid YYYY-MM-DD", err)

    def test_invalid_date_nonexistent_day(self):
        args = [
            "caseledger", "--file", self.filepath,
            "add", "--code", "X2", "--title", "Feb 30",
            "--team", "dev", "--priority", "1", "--due-date", "2026-02-30",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("not a valid YYYY-MM-DD", err)

    def test_zero_priority_rejected(self):
        args = [
            "caseledger", "--file", self.filepath,
            "add", "--code", "X3", "--title", "Zero pri",
            "--team", "dev", "--priority", "0", "--due-date", "2026-12-01",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("priority must be greater than 0", err)

    def test_negative_priority_rejected(self):
        args = [
            "caseledger", "--file", self.filepath,
            "add", "--code", "X4", "--title", "Neg pri",
            "--team", "dev", "--priority", "-1", "--due-date", "2026-12-01",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("priority must be greater than 0", err)


class TestInvalidStatusFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name
        save_cases([], self.filepath)

    def tearDown(self):
        os.unlink(self.filepath)

    def test_list_invalid_status(self):
        args = [
            "caseledger", "--file", self.filepath,
            "list", "--status", "nonexistent",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("invalid status", err)

    def test_export_csv_invalid_status(self):
        args = [
            "caseledger", "--file", self.filepath,
            "export-csv", "--status", "fake",
        ]
        code, _, err = _run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn("invalid status", err)


class TestReportTieBreaking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        )
        self.tmp.close()
        self.filepath = self.tmp.name

    def tearDown(self):
        os.unlink(self.filepath)

    def test_same_priority_sorted_by_due_then_code(self):
        cases = [
            {
                "code": "Z001", "title": "Later due", "team": "dev",
                "priority": 1, "due_date": "2026-08-01", "note": "",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
            {
                "code": "A001", "title": "Earlier due", "team": "dev",
                "priority": 1, "due_date": "2026-07-01", "note": "",
                "status": "doing", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
            {
                "code": "A000", "title": "Same due smaller code", "team": "dev",
                "priority": 1, "due_date": "2026-07-01", "note": "",
                "status": "open", "created_at": "2026-01-01T00:00:00",
                "history": [],
            },
        ]
        save_cases(cases, self.filepath)
        args = [
            "caseledger", "--file", self.filepath, "report",
        ]
        code, out, _ = _run_cli(args)
        self.assertEqual(code, 0)
        self.assertIn("A000", out)
        self.assertIn("highest priority unclosed: A000", out)
