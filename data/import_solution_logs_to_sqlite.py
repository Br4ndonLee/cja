#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import csv
import sqlite3
from typing import Any, List, Tuple


def table_name_from_csv_path(csv_path: str) -> str:
    """Derive table name from CSV file name (without extension)."""
    base = os.path.basename(csv_path)
    name, _ = os.path.splitext(base)
    return name


def fetch_table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return column names of a table using PRAGMA table_info."""
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    rows = cur.fetchall()
    return [r[1] for r in rows]  # name column


def try_cast(v: Any) -> Any:
    """Best-effort cast: int -> float -> keep string. Empty -> None."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    # int
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            return int(s)
        except Exception:
            pass
    # float
    try:
        return float(s)
    except Exception:
        return s


def looks_like_datetime(s: str) -> bool:
    """Heuristic check for 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS'."""
    s = s.strip()
    if len(s) < 16:
        return False
    # very lightweight check
    return (
        s[4] == "-" and s[7] == "-" and s[10] == " " and s[13] == ":" and s[:4].isdigit()
    )


def detect_header(first_row: List[str], table_cols: List[str]) -> bool:
    """
    Decide whether first_row is a header.
    Rules:
      1) If any cell equals a table column name -> header
      2) If first cell looks like datetime -> likely data (no header)
    """
    row_norm = [c.strip() for c in first_row]
    if any(c in table_cols for c in row_norm):
        return True
    if row_norm and looks_like_datetime(row_norm[0]):
        return False
    # fallback: if all are non-numeric-ish words, treat as header
    # but keep it conservative
    return False


def insert_many(
    conn: sqlite3.Connection,
    table: str,
    cols: List[str],
    values_rows: List[List[Any]],
    chunk_size: int = 1000,
) -> int:
    """Bulk insert rows."""
    col_sql = ", ".join([f'"{c}"' for c in cols])
    ph = ", ".join(["?"] * len(cols))
    sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({ph})'

    total = 0
    cur = conn.cursor()
    for i in range(0, len(values_rows), chunk_size):
        chunk = values_rows[i : i + chunk_size]
        cur.executemany(sql, chunk)
        total += cur.rowcount
    return total


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python3 csv_append_to_table.py /path/to/data.db /path/to/TableName.csv\n"
            "Optional:\n"
            "  --table TableName   # override table name\n"
            "  --chunksize N       # default 1000\n",
            file=sys.stderr,
        )
        sys.exit(2)

    db_path = sys.argv[1]
    csv_path = sys.argv[2]

    table = table_name_from_csv_path(csv_path)
    chunk_size = 1000

    args = sys.argv[3:]
    i = 0
    while i < len(args):
        if args[i] == "--table" and i + 1 < len(args):
            table = args[i + 1]
            i += 2
        elif args[i] == "--chunksize" and i + 1 < len(args):
            chunk_size = int(args[i + 1])
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(2)

    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(csv_path):
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        table_cols = fetch_table_columns(conn, table)
        if not table_cols:
            raise ValueError(f"Table does not exist or has no columns: {table}")

        # Read CSV as raw rows first (works with or without header)
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            first = next(reader, None)
            if first is None:
                raise ValueError("CSV is empty.")

            has_header = detect_header(first, table_cols)

            values_rows: List[List[Any]] = []

            if has_header:
                # Use DictReader with the detected header
                header = [h.strip() for h in first]
                dict_reader = csv.DictReader(f, fieldnames=header)
                # We already consumed first line as header, so start from next line
                for row in dict_reader:
                    # Keep only columns that exist in table
                    vals = []
                    cols = []
                    for k, v in row.items():
                        k = (k or "").strip()
                        if k in table_cols:
                            cols.append(k)
                            vals.append(try_cast(v))
                    if cols:
                        # Insert using matched columns only
                        # To avoid varying cols per row, we require stable cols set
                        pass
                # Re-read properly with DictReader from scratch to keep stable cols set
                f.seek(0)
                dict_reader2 = csv.DictReader(f)
                header2 = [h.strip() for h in (dict_reader2.fieldnames or [])]
                use_cols = [c for c in header2 if c in table_cols]
                if not use_cols:
                    raise ValueError(
                        f"No matching columns between CSV headers and table '{table}'.\n"
                        f"CSV headers: {header2}\n"
                        f"Table cols : {table_cols}"
                    )
                for row in dict_reader2:
                    values_rows.append([try_cast(row.get(c)) for c in use_cols])

                with conn:
                    inserted = insert_many(conn, table, use_cols, values_rows, chunk_size)

            else:
                # No header: map CSV columns to table columns by POSITION
                cols = table_cols[:]  # full column order

                # First row is data
                def pad_or_trim(r: List[str], n: int) -> List[Any]:
                    r2 = [try_cast(x) for x in r]
                    if len(r2) >= n:
                        return r2[:n]
                    return r2 + [None] * (n - len(r2))

                values_rows.append(pad_or_trim(first, len(cols)))

                for r in reader:
                    if not r or all((str(x).strip() == "" for x in r)):
                        continue
                    values_rows.append(pad_or_trim(r, len(cols)))

                with conn:
                    inserted = insert_many(conn, table, cols, values_rows, chunk_size)

        print(f"OK: inserted {inserted} rows into '{table}' from '{csv_path}' (header={has_header})")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
