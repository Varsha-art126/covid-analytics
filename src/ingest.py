"""
ingest.py — COVID-19 Analytics ETL pipeline

Downloads the Our World in Data COVID-19 dataset, cleans it with pandas,
and loads it into a SQLite database designed in sql/schema.sql.

Usage:
    python src/ingest.py            # download (with cache) + load
    python src/ingest.py --fresh    # force re-download of the raw CSV
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --- project layout ---------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_CSV = RAW_DIR / "owid-covid-data.csv"
DB_PATH = DATA_DIR / "covid_analytics.db"

DATA_URL = ("https://raw.githubusercontent.com/owid/covid-19-data/"
            "master/public/data/owid-covid-data.csv")

# Columns we keep from the OWID export (the full export has 60+ columns)
COLUMN_MAP = {
    "iso_code": "country_code",
    "location": "location",
    "continent": "continent",
    "date": "date",
    "population": "population",
    "population_density": "population_density",
    "median_age": "median_age",
    "aged_65_older": "aged_65_older",
    "gdp_per_capita": "gdp_per_capita",
    "extreme_poverty": "extreme_poverty",
    "cardiovasc_death_rate": "cardiovasc_death_rate",
    "diabetes_prevalence": "diabetes_prevalence",
    "life_expectancy": "life_expectancy",
    "human_development_index": "human_development_index",
    "hospital_beds_per_thousand": "hospital_beds_per_thousand",
    "total_cases": "total_cases",
    "new_cases": "new_cases",
    "new_cases_smoothed": "new_cases_smoothed",
    "total_deaths": "total_deaths",
    "new_deaths": "new_deaths",
    "new_deaths_smoothed": "new_deaths_smoothed",
    "hosp_patients": "hosp_patients",
    "icu_patients": "icu_patients",
    "reproduction_rate": "reproduction_rate",
    "total_tests": "total_tests",
    "new_tests": "new_tests",
    "total_vaccinations": "total_vaccinations",
    "new_vaccinations": "new_vaccinations",
    "new_vaccinations_smoothed": "new_vaccinations_smoothed",
    "people_vaccinated": "people_vaccinated",
    "people_fully_vaccinated": "people_fully_vaccinated",
    "people_fully_vaccinated_per_hundred": "people_fully_vaccinated_per_hundred",
}

NUMERIC_COLS = [
    "population", "population_density", "median_age", "aged_65_older",
    "gdp_per_capita", "extreme_poverty", "cardiovasc_death_rate",
    "diabetes_prevalence", "life_expectancy", "human_development_index",
    "hospital_beds_per_thousand", "total_cases", "new_cases",
    "new_cases_smoothed", "total_deaths", "new_deaths", "new_deaths_smoothed",
    "hosp_patients", "icu_patients", "reproduction_rate", "total_tests",
    "new_tests", "total_vaccinations", "new_vaccinations",
    "new_vaccinations_smoothed", "people_vaccinated",
    "people_fully_vaccinated", "people_fully_vaccinated_per_hundred",
]

CHUNK_SIZE = 200_000  # rows per chunk — keeps memory usage moderate

# --- column groups shared by ingest() and tests -----------------------------
# dimension cols: iso_code, location, continent + the 11 country attributes
_DIM_KEYS = list(COLUMN_MAP)[0:3] + list(COLUMN_MAP)[4:15]
# fact cols: keys + date + epidemic metrics (not the country attributes,
# which live only in the countries dimension)
_FACT_KEYS = ["iso_code", "date"] + list(COLUMN_MAP)[15:]

countries_cols = [COLUMN_MAP[k] for k in _DIM_KEYS]
fact_cols = [COLUMN_MAP[k] for k in _FACT_KEYS]


def download_csv(force: bool = False) -> Path:
    """Stream-download the OWID CSV with a simple resume/cache strategy."""
    import requests

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if RAW_CSV.exists() and not force:
        age_h = (time.time() - RAW_CSV.stat().st_mtime) / 3600
        print(f"[cache] using existing {RAW_CSV.name} ({age_h:.1f} h old)")
        return RAW_CSV

    print(f"[download] {DATA_URL}")
    tmp = RAW_CSV.with_suffix(".part")
    with requests.get(DATA_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r[download] {pct:5.1f}% ({done/1e6:.0f}/{total/1e6:.0f} MB)",
                          end="", flush=True)
    print()
    tmp.replace(RAW_CSV)
    print(f"[download] saved -> {RAW_CSV} ({RAW_CSV.stat().st_size/1e6:.1f} MB)")
    return RAW_CSV


def clean_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Normalize one raw chunk into the schema's shape and dtypes."""
    chunk = chunk[list(COLUMN_MAP)].rename(columns=COLUMN_MAP)

    # Keep real countries only: OWID includes continents ('Asia'), income
    # groups ('High-income countries'), and 'OWID_WRL' world aggregates.
    chunk = chunk[chunk["continent"].notna()].copy()

    # Types + hygiene
    chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    chunk[NUMERIC_COLS] = chunk[NUMERIC_COLS].apply(pd.to_numeric, errors="coerce")
    for col in ("location", "continent", "country_code"):
        chunk[col] = chunk[col].astype("string").str.strip()

    # Drop rows that lost their date in coercion
    chunk = chunk[chunk["date"].notna()]

    # Negative daily counts are reporting artifacts — clamp to 0
    for col in ("new_cases", "new_deaths", "new_tests", "new_vaccinations"):
        chunk.loc[chunk[col] < 0, col] = 0.0

    # country_code is the FK; without it the row is unusable
    chunk = chunk[chunk["country_code"].notna() & (chunk["country_code"] != "")]
    return chunk


def insert_fact(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """INSERT OR IGNORE so duplicate (country_code, date) rows never abort the load."""
    cols = list(df.columns)
    sql = (f"INSERT OR IGNORE INTO daily_stats ({','.join(cols)}) "
           f"VALUES ({','.join('?' for _ in cols)})")
    records = df.astype(object).where(pd.notna(df), None).values.tolist()
    conn.executemany(sql, records)


def ingest(csv_path: Path) -> dict:
    """Clean the CSV in chunks and load into SQLite. Returns run stats."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # rebuild from scratch each run for reproducibility
        print(f"[db] removed old {DB_PATH.name}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))

    stats = {"rows": 0, "countries": 0}
    t0 = time.time()

    for i, chunk in enumerate(pd.read_csv(csv_path, chunksize=CHUNK_SIZE)):
        clean = clean_chunk(chunk)
        if clean.empty:
            continue

        # --- dimension load: static per-country attributes ---
        dims = (clean[countries_cols]
                .dropna(subset=["location", "continent"])
                .sort_values("population", na_position="last")
                .drop_duplicates(subset="country_code", keep="last"))
        dim_sql = (f"INSERT OR IGNORE INTO countries ({','.join(dims.columns)}) "
                   f"VALUES ({','.join('?' for _ in dims.columns)})")
        conn.executemany(dim_sql, dims.astype(object)
                         .where(pd.notna(dims), None).values.tolist())

        # world aggregate row: excluded from daily_stats (it would double-count
        # in per-country sums) but kept in `countries` for global KPI queries.
        # Take it from the raw chunk — clean_chunk drops aggregate rows by design.
        world = chunk[chunk["iso_code"] == "OWID_WRL"]
        if not world.empty:
            w = (world.rename(columns=COLUMN_MAP)[countries_cols]
                 .drop_duplicates(subset="country_code"))
            conn.executemany(dim_sql, w.astype(object)
                             .where(pd.notna(w), None).values.tolist())

        # --- fact load: daily observations (no descriptive cols) ---
        insert_fact(conn, clean[fact_cols])
        stats["rows"] += len(clean)

        print(f"\r[load] chunk {i + 1}: {stats['rows']:,} rows so far", end="")

    print()

    conn.commit()
    stats["rows"] = conn.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0]
    stats["countries"] = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    stats["min_date"], stats["max_date"] = conn.execute(
        "SELECT MIN(date), MAX(date) FROM daily_stats").fetchone()

    # metadata row
    conn.execute(
        "INSERT INTO ingestion_log (source, ingested_at, rows_loaded, "
        "countries_loaded, min_date, max_date) VALUES (?, ?, ?, ?, ?, ?)",
        (DATA_URL, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         stats["rows"], stats["countries"], stats["min_date"], stats["max_date"]),
    )
    conn.commit()
    conn.close()

    print(f"[db] {stats['rows']:,} rows | {stats['countries']} countries | "
          f"{stats['min_date']} -> {stats['max_date']} | {time.time()-t0:.0f}s")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="COVID-19 analytics ETL")
    parser.add_argument("--fresh", action="store_true",
                        help="force re-download of the raw CSV")
    args = parser.parse_args()

    csv_path = download_csv(force=args.fresh)
    stats = ingest(csv_path)
    print("[done] database ready:", DB_PATH)


if __name__ == "__main__":
    sys.exit(main())
