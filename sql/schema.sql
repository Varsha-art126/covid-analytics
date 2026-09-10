-- ============================================================
-- COVID-19 Analytics — SQLite schema
-- Source: Our World in Data (owid-covid-data.csv)
-- One dimension table (countries) + one fact table (daily_stats)
-- ============================================================

PRAGMA foreign_keys = ON;

-- ---------- Dimension: one row per country ----------
-- continent is nullable: the OWID_WRL (world aggregate) row has none, and
-- dashboards use `continent IS NOT NULL` to exclude aggregates from lists.
DROP TABLE IF EXISTS countries;
CREATE TABLE countries (
    country_code              TEXT PRIMARY KEY,   -- ISO 3166-1 alpha-3 (OWID iso_code)
    location                  TEXT NOT NULL,
    continent                 TEXT,
    population                REAL,
    population_density        REAL,
    median_age                REAL,
    aged_65_older             REAL,               -- share of population aged 65+
    gdp_per_capita            REAL,               -- international-$, 2011 PPP
    extreme_poverty           REAL,               -- share of population
    cardiovasc_death_rate     REAL,               -- annual deaths per 100k
    diabetes_prevalence       REAL,               -- % of population
    life_expectancy           REAL,
    human_development_index   REAL,
    hospital_beds_per_thousand REAL
);

-- ---------- Fact: one row per country per day ----------
DROP TABLE IF EXISTS daily_stats;
CREATE TABLE daily_stats (
    country_code                    TEXT NOT NULL REFERENCES countries(country_code),
    date                            TEXT NOT NULL,     -- ISO date 'YYYY-MM-DD'
    new_cases                       REAL,
    new_cases_smoothed              REAL,              -- 7-day avg
    total_cases                     REAL,
    new_deaths                      REAL,
    new_deaths_smoothed             REAL,
    total_deaths                    REAL,
    hosp_patients                   REAL,              -- hospitalized on that day
    icu_patients                    REAL,
    reproduction_rate               REAL,              -- R_t estimate
    new_tests                       REAL,
    total_tests                     REAL,
    new_vaccinations                REAL,
    new_vaccinations_smoothed       REAL,
    total_vaccinations              REAL,              -- doses administered (incl. boosters)
    people_vaccinated               REAL,              -- at least 1 dose
    people_fully_vaccinated         REAL,              -- full primary series
    people_fully_vaccinated_per_hundred REAL,
    PRIMARY KEY (country_code, date)
);

-- ---------- Operational metadata ----------
CREATE TABLE IF NOT EXISTS ingestion_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    ingested_at  TEXT NOT NULL,                        -- UTC timestamp
    rows_loaded  INTEGER NOT NULL,
    countries_loaded INTEGER NOT NULL,
    min_date     TEXT,
    max_date     TEXT
);

-- ---------- Indexes tuned for the analysis queries ----------
CREATE INDEX IF NOT EXISTS idx_daily_date        ON daily_stats(date);
CREATE INDEX IF NOT EXISTS idx_daily_new_cases   ON daily_stats(country_code, date, new_cases_smoothed);
CREATE INDEX IF NOT EXISTS idx_daily_vax         ON daily_stats(country_code, date, people_fully_vaccinated_per_hundred);
