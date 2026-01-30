#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
csv_to_sqlite.py
- Import multiple CSV files into a single SQLite database.
- One table per CSV file (table name derived from filename).
- Auto-infers column types (INTEGER/REAL/TEXT) using a small sample.
- Uses streaming insert with batching for large files.
"""

import argparse
import csv
import glob
import os
import re
import sqlite3
from typing import Dict, List, Tuple, Optional

# ---------- Helpers: naming & type inference ----------

def sanitize_identifier(name: str) -> str:
    """Sanitize a string to be a safe SQLite identifier."""
    name = name.strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^0-9a-zA-Z_]", "_", name)
    if not name:
        name = "col"
    # SQLite allows identifiers starting with digits if quoted, but we will quote anyway.
    return name

def table_name_from_path(csv_path: str) -> str:
    """Derive table name from the CSV filename."""
    base = os.path.basename(csv_path)
    name = os.path.splitext(base)[0]
    return sanitize_identifier(name)

def try_parse_int(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False

def try_parse_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False

def infer_sqlite_type(values: List[str]) -> str:
    """
    Infer SQLite type from a list of string values.
    Rules:
      - If all non-empty values parse as int -> INTEGER
      - Else if all non-empty values parse as float -> REAL
      - Else -> TEXT
    """
    non_empty = [v.strip() for v in values if v is not None and str(v).strip() != ""]
    if not non_empty:
        return "TEXT"

    if all(try_parse_int(v) for v in non_empty):
        return "INTEGER"
    if all(try_parse_float(v) for v in non_empty):
        return "REAL"
    return "TEXT"

def pick_time_like_column(cols: List[str]) -> Optional[str]:
    """Pick a likely time column for indexing if present."""
    candidates = ["date", "datetime", "timestamp", "time", "ts", "created_at"]
    lower_map = {c.lower(): c for c in cols}
    for k in candidates:
        if k in lower_map:
            return lower_map[k]
    return None

# ---------- Core import logic ----------

def read_header_and_sample(csv_path: str, encoding: str, delimiter: str, sample_rows: int) -> Tuple[List[str], List[List[str]]]:
    """Read header and first N rows as sample."""
    with open(csv_path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"Empty CSV: {csv_path}")
        sample = []
        for _ in range(sample_rows):
            row = next(reader, None)
            if row is None:
                break
            sample.append(row)
    return header, sample

def build_schema(header: List[str], sample_rows: List[List[str]]) -> Tuple[List[str], Dict[str, str]]:
    """Create sanitized column names and infer types using sample rows."""
    # Sanitize column names and ensure uniqueness
    seen = {}
    cols = []
    for raw in header:
        col = sanitize_identifier(raw)
        if col in seen:
            seen[col] += 1
            col = f"{col}_{seen[col]}"
        else:
            seen[col] = 0
        cols.append(col)

    # Transpose sample rows to infer types per column
    col_values = {cols[i]: [] for i in range(len(cols))}
    for r in sample_rows:
        # Pad shorter rows to match header length
        padded = r + [""] * (len(cols) - len(r))
        for i, col in enumerate(cols):
            col_values[col].append(padded[i])

    types = {col: infer_sqlite_type(col_values[col]) for col in cols}
    return cols, types

def create_table(conn: sqlite3.Connection, table: str, cols: List[str], types: Dict[str, str], add_pk: bool) -> None:
    """Create table if not exists."""
    cur = conn.cursor()

    col_defs = []
    if add_pk:
        # Use an auto-incrementing integer primary key for stability
        col_defs.append('"id" INTEGER PRIMARY KEY AUTOINCREMENT')

    for c in cols:
        col_defs.append(f'"{c}" {types[c]}')

    sql = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)});'
    cur.execute(sql)
    conn.commit()

def create_index_if_time(conn: sqlite3.Connection, table: str, time_col: Optional[str]) -> None:
    """Create index on a time-like column if present."""
    if not time_col:
        return
    cur = conn.cursor()
    idx_name = f"idx_{table}_{sanitize_identifier(time_col)}"
    cur.execute(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{table}"("{sanitize_identifier(time_col)}");')
    conn.commit()

def prepare_insert_sql(table: str, cols: List[str]) -> str:
    """Prepare INSERT statement for given columns."""
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join([f'"{c}"' for c in cols])
    return f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders});'

def normalize_row(row: List[str], n_cols: int) -> List[Optional[str]]:
    """Pad/truncate row to match column count; keep values as strings (SQLite will coerce types)."""
    padded = row + [""] * (n_cols - len(row))
    trimmed = padded[:n_cols]
    # Convert empty strings to None to store NULL (optional; comment out if you prefer "")
    return [None if (v is None or str(v).strip() == "") else v for v in trimmed]

def import_csv_to_table(
    conn: sqlite3.Connection,
    csv_path: str,
    table: str,
    cols: List[str],
    insert_sql: str,
    encoding: str,
    delimiter: str,
    batch_size: int,
    skip_header: bool = True,
) -> int:
    """Stream-import CSV rows into SQLite table. Returns number of inserted rows."""
    cur = conn.cursor()
    inserted = 0
    batch = []
    n_cols = len(cols)

    with open(csv_path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        if skip_header:
            _ = next(reader, None)

        for row in reader:
            batch.append(normalize_row(row, n_cols))
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                inserted += len(batch)
                batch.clear()

        if batch:
            cur.executemany(insert_sql, batch)
            inserted += len(batch)
            batch.clear()

    conn.commit()
    return inserted

def main():
    parser = argparse.ArgumentParser(description="Convert CSV files to SQLite (one table per CSV).")
    parser.add_argument("--input", required=True, help="Input CSV glob (e.g., '/path/*.csv') or a directory.")
    parser.add_argument("--db", required=True, help="Output SQLite DB path (e.g., '/path/data.db').")
    parser.add_argument("--encoding", default="utf-8", help="CSV encoding (default: utf-8). Try 'utf-8-sig' or 'cp949' if needed.")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: ',').")
    parser.add_argument("--sample-rows", type=int, default=200, help="Rows used for type inference (default: 200).")
    parser.add_argument("--batch-size", type=int, default=2000, help="Insert batch size (default: 2000).")
    parser.add_argument("--add-pk", action="store_true", help="Add auto-increment primary key column named 'id'.")
    parser.add_argument("--drop", action="store_true", help="Drop existing tables before import.")
    args = parser.parse_args()

    # Resolve input paths
    if os.path.isdir(args.input):
        csv_paths = sorted(glob.glob(os.path.join(args.input, "*.csv")))
    else:
        csv_paths = sorted(glob.glob(args.input))

    if not csv_paths:
        raise SystemExit(f"No CSV files found for input: {args.input}")

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)

    conn = sqlite3.connect(args.db)
    # Performance-related pragmas (safe defaults)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        for csv_path in csv_paths:
            table = table_name_from_path(csv_path)

            header, sample = read_header_and_sample(
                csv_path=csv_path,
                encoding=args.encoding,
                delimiter=args.delimiter,
                sample_rows=args.sample_rows,
            )
            cols, types = build_schema(header, sample)

            cur = conn.cursor()
            if args.drop:
                cur.execute(f'DROP TABLE IF EXISTS "{table}";')
                conn.commit()

            create_table(conn, table, cols, types, add_pk=args.add_pk)

            # Create time-like index if any
            time_col = pick_time_like_column(cols)
            create_index_if_time(conn, table, time_col)

            insert_cols = cols  # do not include PK
            insert_sql = prepare_insert_sql(table, insert_cols)

            inserted = import_csv_to_table(
                conn=conn,
                csv_path=csv_path,
                table=table,
                cols=insert_cols,
                insert_sql=insert_sql,
                encoding=args.encoding,
                delimiter=args.delimiter,
                batch_size=args.batch_size,
                skip_header=True,
            )

            print(f"[OK] {os.path.basename(csv_path)} -> table '{table}' ({inserted} rows)")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
