"""
test_app.py — smoke tests for the ETL cleaning logic and dashboard SQL.

Run:
    .venv/Scripts/python -m pytest tests/ -v
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "covid_analytics.db"


# --------------------------------------------------------------------------
# ETL cleaning logic
# --------------------------------------------------------------------------
def _raw_frame(**overrides):
    """Build a one-row-per-entry raw frame containing every OWID column."""
    base = {k: [None] * len(next(iter(overrides.values())))
            if overrides else [None] for k in COLUMN_MAP_KEYS}
    base.update({k: list(v) for k, v in overrides.items()})
    return pd.DataFrame(base)


def test_clean_chunk_drops_aggregates():
    from src.ingest import clean_chunk

    raw = _raw_frame(
        iso_code=["OWID_WRL", "IND", "IND"],
        location=["World", "India", "India"],
        continent=[None, "Asia", "Asia"],
        date=["2021-05-01", "2021-05-01", "2021-05-02"],
        population=[7.8e9, 1.4e9, 1.4e9],
        new_cases=[800000.0, 300000.0, -500.0],  # negative = reporting artifact
    )
    out = clean_chunk(raw)
    assert "OWID_WRL" not in out["country_code"].values   # world row dropped
    assert (out["new_cases"] >= 0).all()                  # negatives clamped


def test_clean_chunk_output_matches_fact_columns():
    from src.ingest import COLUMN_MAP, clean_chunk, fact_cols

    raw = _raw_frame(iso_code=["IND"], location=["India"],
                     continent=["Asia"], date=["2021-05-01"])
    out = clean_chunk(raw)
    # clean keeps every mapped column; slicing to fact cols happens at load
    assert set(out.columns) == set(COLUMN_MAP.values())
    assert set(fact_cols).issubset(set(out.columns))


COLUMN_MAP_KEYS = [
    "iso_code", "location", "continent", "date", "population",
    "population_density", "median_age", "aged_65_older", "gdp_per_capita",
    "extreme_poverty", "cardiovasc_death_rate", "diabetes_prevalence",
    "life_expectancy", "human_development_index", "hospital_beds_per_thousand",
    "total_cases", "new_cases", "new_cases_smoothed", "total_deaths",
    "new_deaths", "new_deaths_smoothed", "hosp_patients", "icu_patients",
    "reproduction_rate", "total_tests", "new_tests", "total_vaccinations",
    "new_vaccinations", "new_vaccinations_smoothed", "people_vaccinated",
    "people_fully_vaccinated", "people_fully_vaccinated_per_hundred",
]


# --------------------------------------------------------------------------
# Database sanity (skipped if ingestion hasn't run yet)
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def db():
    if not DB_PATH.exists():
        pytest.skip("database not built yet — run src/ingest.py first")
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def test_db_has_data(db):
    n = db.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0]
    assert n > 300_000


def test_no_world_rows_in_fact_table(db):
    n = db.execute(
        "SELECT COUNT(*) FROM daily_stats WHERE country_code = 'OWID_WRL'"
    ).fetchone()[0]
    assert n == 0


def test_no_negative_daily_counts(db):
    n = db.execute(
        "SELECT COUNT(*) FROM daily_stats WHERE new_cases < 0 OR new_deaths < 0"
    ).fetchone()[0]
    assert n == 0


def test_fk_integrity(db):
    orphans = db.execute(
        "SELECT COUNT(*) FROM daily_stats d "
        "LEFT JOIN countries c USING (country_code) WHERE c.country_code IS NULL"
    ).fetchone()[0]
    assert orphans == 0


# --------------------------------------------------------------------------
# Dashboard SQL smoke tests (same statements app.py runs)
# --------------------------------------------------------------------------
def test_world_kpis(db):
    # world aggregate must exist in `countries` (not daily_stats)
    pop = db.execute(
        "SELECT population FROM countries WHERE country_code = 'OWID_WRL'"
    ).fetchone()[0]
    assert pop and pop > 7e9

    # dashboard KPI query: sum of per-country peak cumulative values
    cases, deaths = db.execute("""
        SELECT SUM(cases), SUM(deaths) FROM (
            SELECT MAX(total_cases) AS cases, MAX(total_deaths) AS deaths
            FROM daily_stats GROUP BY country_code)
    """).fetchone()
    assert cases > 700_000_000 and deaths > 6_000_000


def test_country_series_sql(db):
    import pandas as pd
    sql = """
        SELECT d.date, d.new_cases_smoothed
        FROM daily_stats d JOIN countries c USING (country_code)
        WHERE c.location = ? ORDER BY d.date
    """
    df = pd.read_sql_query(sql, db, params=("India",))
    assert len(df) > 1000 and df["new_cases_smoothed"].notna().any()


def test_vaccination_sql(db):
    sql = """
        SELECT c.location,
               MAX(d.people_fully_vaccinated_per_hundred) AS fully_vax_pct
        FROM daily_stats d JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL AND c.population >= 1000000
        GROUP BY d.country_code HAVING fully_vax_pct <= 100
    """
    df = pd.read_sql_query(sql, db)
    assert len(df) > 100 and df["fully_vax_pct"].between(0, 100).all()
