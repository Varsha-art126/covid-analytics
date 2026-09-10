"""
run_queries.py — execute every analysis query in sql/queries.sql against the
SQLite database and print a preview of each result.

Usage:
    python src/run_queries.py
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "covid_analytics.db"
QUERIES = ROOT / "sql" / "queries.sql"


def load_statements(path: Path) -> list[str]:
    """Split the .sql file into individual statements (no ';' in literals here)."""
    text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.strip().startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    statements = load_statements(QUERIES)
    print(f"Running {len(statements)} analysis queries against {DB_PATH.name}\n")

    for i, stmt in enumerate(statements, 1):
        title = next((ln.lstrip("- ").strip() for ln in stmt.splitlines()), f"Q{i}")
        try:
            df = pd.read_sql_query(stmt, conn)
        except Exception as exc:
            print(f"Q{i} FAILED — {title}\n  {exc}\n")
            sys.exit(1)
        print(f"Q{i}: {title}  [{len(df)} rows]")
        print(df.head(5).to_string(index=False), "\n")

    conn.close()
    print("All queries executed successfully.")


if __name__ == "__main__":
    main()
