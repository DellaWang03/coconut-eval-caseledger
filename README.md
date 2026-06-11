# CaseLedger

A pure-Python (standard library only) CLI tool for case/ticket tracking. Data is stored in a JSONL file.

## Installation

No installation needed. Run directly with:

```bash
python3 -m caseledger <command> [options]
```

## Data File

By default, cases are stored in `cases.jsonl` in the current directory. Override with `--file path/to/file.jsonl` or set `CASELEDGER_FILE` environment variable.

## Status Rules

Cases follow a strict state machine:

```
open → doing → blocked → closed
                 ↘
          doing → resolved → closed
```

Valid transitions:
- `open` → `doing`
- `doing` → `blocked` | `resolved`
- `blocked` → `closed`
- `resolved` → `closed`

Any other transition is rejected.

## Commands

### add — Create a new case

```bash
python3 -m caseledger add \
  --code "CASE 001" \
  --title "Fix login timeout" \
  --team dev \
  --priority 1 \
  --due-date 2026-07-01 \
  --note "Reported by customer X"
```

- `code` is normalized: spaces stripped, converted to uppercase. Must be unique.
- `priority` is an integer (1 = highest).

### update — Change case status

```bash
python3 -m caseledger update --code CASE001 --status doing
python3 -m caseledger update --code CASE001 --status resolved
python3 -m caseledger update --code CASE001 --status closed
```

Each update appends to the case history.

### list — List and filter cases

```bash
python3 -m caseledger list
python3 -m caseledger list --team dev
python3 -m caseledger list --status open
python3 -m caseledger list --q "login"
python3 -m caseledger list --team ops --status doing
```

Results are sorted by priority (ascending), then due_date, then code.

### report — Team status report

```bash
python3 -m caseledger report
```

Outputs per team:
- Status counts
- Number of overdue unclosed cases (due_date < today and status ≠ closed)
- Highest priority unclosed case

### export-csv — Export filtered results to CSV

```bash
python3 -m caseledger export-csv --output cases.csv
python3 -m caseledger export-csv --team dev --output dev_cases.csv
python3 -m caseledger export-csv --status open --q "urgent"
```

Without `--output`, writes to stdout.

## Running Tests

```bash
python3 -m unittest discover -v
```
