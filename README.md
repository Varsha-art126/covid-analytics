# 🦠 COVID-19 Global Analytics

A medium-sized, end-to-end data analytics project: **real data → Python ETL →
SQL analysis → interactive dashboard**.

**Data source:** [Our World in Data — COVID-19 dataset](https://github.com/owid/covid-19-data)
(~98 MB CSV, ~430k country-day records, Jan 2020 – Aug 2024, 236 countries).

## What it answers

- Which countries were hit hardest — in absolute numbers and per capita?
- How did case fatality rates differ across continents?
- Where did each pandemic wave peak, and when did vaccinations start?
- Do development indicators (GDP, median age, health spending) correlate with
  COVID mortality?

Headline findings from the current build: US, China, and India lead absolute
cases; **Peru has the highest deaths per million (6,490)**; South America has
the worst CFR (1.97%); the first G20 vaccine dose was given in the US on
**2020-12-14**; and the single deadliest month was **China's Dec 2022 exit
wave (52.8 M cases)**.

## Project structure

```
covid_analytics/
├── data/                     # raw CSV + SQLite DB (gitignored, auto-built)
├── sql/
│   ├── schema.sql            # star-style schema: countries + daily_stats
│   └── queries.sql           # 10 reusable analysis questions in pure SQL
├── src/
│   ├── ingest.py             # ETL: download → clean (chunks) → SQLite
│   └── run_queries.py        # executes queries.sql, prints previews
├── notebooks/
│   └── 01_eda.ipynb          # executed EDA notebook (7 interactive charts)
├── scripts/
│   └── make_notebook.py      # regenerates the notebook programmatically
├── tests/
│   └── test_app.py           # 9 smoke tests: ETL logic, DB integrity, SQL
├── app.py                    # Streamlit dashboard (3 views)
└── requirements.txt
```

## Quickstart

```bash
cd covid_analytics

# 1. environment
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # Linux/Mac

# 2. build the database (downloads ~98 MB, caches it)
.venv/Scripts/python src/ingest.py

# 3. explore
.venv/Scripts/python src/run_queries.py            # 10 SQL questions
.venv/Scripts/jupyter lab notebooks/01_eda.ipynb   # visual EDA
.venv/Scripts/streamlit run app.py                 # dashboard
```

## The pipeline

1. **Download** — streams the OWID CSV with progress + caching (`--fresh`
   forces re-download).
2. **Clean** — in 200k-row chunks: drops continent/income aggregates,
   coerces types, clamps negative daily counts (reporting artifacts),
   dedupes (country, date).
3. **Load** — star-style SQLite schema (dimension `countries`, fact
   `daily_stats`), FK-enforced, indexed for the analysis queries; the world
   aggregate lives in `countries` only so per-country sums never
   double-count. Every run is logged in `ingestion_log`.

## Skills demonstrated

- SQL: joins, CTEs, window functions (`RANK`, `LAG`, `ROW_NUMBER`),
  multi-chunk ETL design, FK + PK constraints, query tuning indexes
- Python: pandas chunked processing, `argparse` CLI design, caching
- Visualization: Streamlit + Plotly (choropleth, time series, treemaps)
- Engineering: pytest suite, reproducible rebuilds, gitignored artifacts

## Notes

- OWID archived this dataset in Aug 2024 — `2024-08-14` is the natural end
  date, not a bug.
- Vaccination % >100 in some territories reflects doses given to visitors;
  country-level analysis filters to population ≥ 1M.
