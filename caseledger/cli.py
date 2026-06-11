"""CLI interface for caseledger."""
import argparse
import csv
import io
import sys
from datetime import datetime

from caseledger.store import load_cases, save_cases, append_case
from caseledger.models import (
    normalize_code,
    validate_transition,
    is_overdue,
    sort_key,
    ALL_STATUSES,
)


def _validate_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _validate_status_filter(status):
    if status and status not in ALL_STATUSES:
        print(
            f"Error: invalid status '{status}'. Must be one of: {', '.join(ALL_STATUSES)}",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_add(args):
    if args.priority < 1:
        print("Error: priority must be greater than 0", file=sys.stderr)
        sys.exit(1)
    if not _validate_date(args.due_date):
        print(
            f"Error: due_date '{args.due_date}' is not a valid YYYY-MM-DD date",
            file=sys.stderr,
        )
        sys.exit(1)
    cases = load_cases(args.file)
    code = normalize_code(args.code)
    for c in cases:
        if c["code"] == code:
            print(f"Error: duplicate code '{code}'", file=sys.stderr)
            sys.exit(1)
    case = {
        "code": code,
        "title": args.title,
        "team": args.team,
        "priority": args.priority,
        "due_date": args.due_date,
        "note": args.note or "",
        "status": "open",
        "created_at": datetime.now().isoformat(),
        "history": [{"status": "open", "ts": datetime.now().isoformat()}],
    }
    append_case(case, args.file)
    print(f"Added: {code}")


def cmd_update(args):
    cases = load_cases(args.file)
    code = normalize_code(args.code)
    found = False
    for case in cases:
        if case["code"] == code:
            found = True
            current = case["status"]
            new_status = args.status
            if not validate_transition(current, new_status):
                print(
                    f"Error: cannot transition from '{current}' to '{new_status}'",
                    file=sys.stderr,
                )
                sys.exit(1)
            case["status"] = new_status
            case["history"].append(
                {"status": new_status, "ts": datetime.now().isoformat()}
            )
            break
    if not found:
        print(f"Error: code '{code}' not found", file=sys.stderr)
        sys.exit(1)
    save_cases(cases, args.file)
    print(f"Updated: {code} -> {new_status}")


def _filter_cases(cases, team=None, status=None, q=None):
    result = cases
    if team:
        result = [c for c in result if c["team"] == team]
    if status:
        result = [c for c in result if c["status"] == status]
    if q:
        ql = q.lower()
        result = [
            c
            for c in result
            if ql in c["code"].lower()
            or ql in c["title"].lower()
            or ql in c.get("note", "").lower()
        ]
    return result


def cmd_list(args):
    _validate_status_filter(args.status)
    cases = load_cases(args.file)
    filtered = _filter_cases(cases, args.team, args.status, args.q)
    filtered.sort(key=sort_key)
    if not filtered:
        print("No cases found.")
        return
    fmt = "{:<12} {:<30} {:<10} {:<4} {:<12} {:<10}"
    print(fmt.format("CODE", "TITLE", "TEAM", "PRI", "DUE", "STATUS"))
    print("-" * 80)
    for c in filtered:
        title = c["title"][:28] if len(c["title"]) > 28 else c["title"]
        print(
            fmt.format(
                c["code"],
                title,
                c["team"],
                c["priority"],
                c.get("due_date") or "-",
                c["status"],
            )
        )


def cmd_report(args):
    cases = load_cases(args.file)
    teams = sorted(set(c["team"] for c in cases))
    if not teams:
        print("No cases.")
        return
    for team in teams:
        team_cases = [c for c in cases if c["team"] == team]
        print(f"\n=== {team} ===")
        status_counts = {}
        for s in ALL_STATUSES:
            cnt = sum(1 for c in team_cases if c["status"] == s)
            if cnt:
                status_counts[s] = cnt
        for s, cnt in status_counts.items():
            print(f"  {s}: {cnt}")
        overdue = [c for c in team_cases if is_overdue(c)]
        print(f"  overdue (unclosed): {len(overdue)}")
        unclosed = [c for c in team_cases if c["status"] != "closed"]
        if unclosed:
            unclosed.sort(key=sort_key)
            top = unclosed[0]
            print(f"  highest priority unclosed: {top['code']} (P{top['priority']})")


def cmd_export_csv(args):
    _validate_status_filter(args.status)
    cases = load_cases(args.file)
    filtered = _filter_cases(cases, args.team, args.status, args.q)
    filtered.sort(key=sort_key)
    output = args.output
    if output:
        f = open(output, "w", newline="", encoding="utf-8")
    else:
        f = sys.stdout
    fieldnames = ["code", "title", "team", "priority", "due_date", "status", "note"]
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for c in filtered:
        writer.writerow(c)
    if output:
        f.close()
        print(f"Exported to {output}")


def main():
    parser = argparse.ArgumentParser(
        prog="caseledger", description="Case tracking ledger CLI"
    )
    parser.add_argument("--file", default=None, help="Path to JSONL data file")
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Add a new case")
    p_add.add_argument("--code", required=True)
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--team", required=True)
    p_add.add_argument("--priority", type=int, required=True)
    p_add.add_argument("--due-date", dest="due_date", required=True)
    p_add.add_argument("--note", default="")

    # update
    p_upd = sub.add_parser("update", help="Update case status")
    p_upd.add_argument("--code", required=True)
    p_upd.add_argument("--status", required=True)

    # list
    p_list = sub.add_parser("list", help="List cases")
    p_list.add_argument("--team", default=None)
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--q", default=None, help="Search query")

    # report
    sub.add_parser("report", help="Team status report")

    # export-csv
    p_csv = sub.add_parser("export-csv", help="Export filtered cases to CSV")
    p_csv.add_argument("--team", default=None)
    p_csv.add_argument("--status", default=None)
    p_csv.add_argument("--q", default=None)
    p_csv.add_argument("--output", "-o", default=None, help="Output file path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "add": cmd_add,
        "update": cmd_update,
        "list": cmd_list,
        "report": cmd_report,
        "export-csv": cmd_export_csv,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
