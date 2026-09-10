"""
make_notebook.py — generate notebooks/01_eda.ipynb programmatically
(so the notebook JSON is always valid).

Run:
    .venv/Scripts/python scripts/make_notebook.py
    .venv/Scripts/jupyter nbconvert --to notebook --execute --inplace notebooks/01_eda.ipynb
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "01_eda.ipynb"


_n = 0


def _id() -> str:
    global _n
    _n += 1
    return f"cell-{_n:02d}"


def code(src: str) -> dict:
    return {"cell_type": "code", "id": _id(), "metadata": {},
            "execution_count": None,
            "outputs": [], "source": src.splitlines(keepends=True)}


def md(src: str) -> dict:
    return {"cell_type": "markdown", "id": _id(), "metadata": {},
            "source": src.splitlines(keepends=True)}


cells = [
    md("""# COVID-19 Analytics — Exploratory Data Analysis

**Data:** [Our World in Data](https://github.com/owid/covid-19-data) · Jan 2020 – Aug 2024
**Database:** `data/covid_analytics.db` (built by `src/ingest.py`)

This notebook explores the SQLite database with SQL first, then drills down
with pandas/plotly for the visual layer."""),

    code("""import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px

DB = Path("..") / "data" / "covid_analytics.db"
conn = sqlite3.connect(DB)

px.defaults.template = "plotly_white"
pd.options.display.float_format = "{:,.1f}".format"""),

    md("## 1. Database tour"),
    code("""for t in ("countries", "daily_stats"):
    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"{t:12s} {n:>9,} rows")

pd.read_sql_query("SELECT * FROM ingestion_log", conn)"""),

    code("""pd.read_sql_query(\"\"\"
    SELECT * FROM countries LIMIT 5
\"\"\", conn)"""),

    md("""## 2. Pandemic waves

Monthly global cases — each peak is a variant wave (Wild type → Alpha →
Delta → Omicron)."""),

    code("""monthly = pd.read_sql_query(\"\"\"
    SELECT SUBSTR(date, 1, 7) AS month,
           SUM(new_cases) AS new_cases,
           SUM(new_deaths) AS new_deaths
    FROM daily_stats WHERE country_code != 'OWID_WRL'
    GROUP BY month ORDER BY month
\"\"\", conn)
monthly["month"] = pd.to_datetime(monthly["month"] + "-01")

px.line(monthly, x="month", y="new_cases",
        title="Global monthly new cases — the pandemic waves")"""),

    code("""fig = px.scatter(monthly, x="new_cases", y="new_deaths",
                 text="month", title="Cases vs deaths by month (2020 → 2024)")
fig.update_traces(textposition="top center", textfont_size=8)
fig"""),

    md("""The months above the trend line killed disproportionately more people per
case — early 2020 (no vaccines, no treatments) and the Delta wave (mid-2021).
Omicron (2022) produced record cases but a much flatter death count."""),

    md("## 3. Country severity: it's not just about case counts"),
    code("""severity = pd.read_sql_query(\"\"\"
    WITH t AS (
        SELECT d.country_code,
               MAX(d.total_cases)  AS cases,
               MAX(d.total_deaths) AS deaths
        FROM daily_stats d
        JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL AND c.population >= 1_000_000
        GROUP BY d.country_code
    )
    SELECT c.location, c.continent, c.gdp_per_capita, c.median_age,
           c.life_expectancy, c.aged_65_older, c.diabetes_prevalence,
           c.cardiovasc_death_rate, c.hospital_beds_per_thousand,
           t.cases * 1e6 / c.population AS cases_per_m,
           t.deaths * 1e6 / c.population AS deaths_per_m,
           100.0 * t.deaths / t.cases    AS cfr_pct
    FROM t JOIN countries c USING (country_code)
    WHERE t.cases > 0
\"\"\", conn)

severity.nlargest(10, "deaths_per_m")[
    ["location", "continent", "cases_per_m", "deaths_per_m", "cfr_pct"]]"""),

    code("""fig = px.treemap(severity, path=[px.Constant("World"), "continent", "location"],
                 values="deaths_per_m", color="cfr_pct",
                 color_continuous_scale="Reds",
                 title="Deaths per million (area) vs CFR % (color)")
fig.update_layout(height=600)
fig"""),

    md("""## 4. Vaccination rollout — who got there first, who got furthest?"""),
    code("""first_vax = pd.read_sql_query(\"\"\"
    SELECT c.location, c.continent, MIN(d.date) AS first_dose
    FROM daily_stats d JOIN countries c USING (country_code)
    WHERE d.new_vaccinations > 0 AND c.population >= 1_000_000
    GROUP BY d.country_code
\"\"\", conn)
first_vax["first_dose"] = pd.to_datetime(first_vax["first_dose"])
first_vax.nsmallest(10, "first_dose")[["location", "first_dose"]]"""),

    code("""vax_speed = pd.read_sql_query(\"\"\"
    SELECT c.location, c.continent,
           MAX(d.people_fully_vaccinated_per_hundred) AS fully_vax_pct
    FROM daily_stats d JOIN countries c USING (country_code)
    WHERE c.continent IS NOT NULL AND c.population >= 1_000_000
    GROUP BY d.country_code HAVING fully_vax_pct <= 100
\"\"\", conn)

px.strip(vax_speed, x="fully_vax_pct", y="continent", color="continent",
         title="Fully vaccinated % by continent — final coverage")"""),

    md("""## 5. India deep-dive (waves & vaccination interplay)"""),
    code("""india = pd.read_sql_query(\"\"\"
    SELECT date, new_cases_smoothed, new_deaths_smoothed,
           people_fully_vaccinated_per_hundred
    FROM daily_stats WHERE country_code = 'IND'
    ORDER BY date
\"\"\", conn)
for c in ("date",):
    india[c] = pd.to_datetime(india[c])

fig = px.line(india, x="date", y="new_cases_smoothed",
              title="India — daily new cases (7-day avg)")
fig.add_scatter(x=india["date"], y=india["new_deaths_smoothed"] * 50,
                mode="lines", name="new deaths ×50 (2nd axis)",
                yaxis="y2")
fig.update_layout(yaxis2={"overlaying": "y", "side": "right"})
fig"""),

    code("""# did vaccination bend the curve? overlay coverage on the death curve
fig = px.area(india, x="date", y="people_fully_vaccinated_per_hundred",
              title="India — fully vaccinated % of population over time")
fig"""),

    md("## 6. Correlation: development indicators vs outcomes"),
    code("""corr_cols = ["gdp_per_capita", "median_age", "life_expectancy",
             "aged_65_older", "diabetes_prevalence", "cardiovasc_death_rate",
             "hospital_beds_per_thousand", "deaths_per_m", "cfr_pct"]
corr = severity[corr_cols].corr().round(2)

fig = px.imshow(corr, text_auto=True, aspect="auto",
                color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                title="Correlation matrix — country traits vs COVID outcomes")
fig.update_layout(height=560)
fig"""),

    code("""conn.close()
print("EDA complete.")"""),
]

nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python",
                       "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print(f"Wrote {OUT} ({len(cells)} cells)")
