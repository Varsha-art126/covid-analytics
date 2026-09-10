-- ============================================================
-- COVID-19 Analytics — analysis questions in pure SQL
-- Run against data/covid_analytics.db, e.g.:
--   sqlite3 data/covid_analytics.db < sql/queries.sql
-- ============================================================

-- Q1. Top 15 countries by cumulative cases (latest snapshot)
SELECT c.location, c.continent, ROUND(MAX(d.total_cases)/1e6, 1) AS total_cases_m
FROM daily_stats d JOIN countries c USING (country_code)
GROUP BY d.country_code
ORDER BY total_cases_m DESC
LIMIT 15;

-- Q2. Deaths per million, top 15 (normalizes for population size)
SELECT c.location, c.continent, c.population,
       ROUND(MAX(d.total_deaths) * 1000000 / c.population, 0) AS deaths_per_million
FROM daily_stats d JOIN countries c USING (country_code)
WHERE c.population > 1_000_000          -- avoid tiny-country distortion
GROUP BY d.country_code
ORDER BY deaths_per_million DESC
LIMIT 15;

-- Q3. Case fatality ratio by continent (weighted by cases, not averaged).
-- Cumulative totals are monotonic, so MAX() gives each country's final value
-- without requiring every country to have data on the same calendar day.
WITH country_totals AS (
    SELECT country_code,
           MAX(total_deaths) AS deaths,
           MAX(total_cases)  AS cases
    FROM daily_stats
    GROUP BY country_code
)
SELECT c.continent,
       ROUND(100.0 * SUM(t.deaths) / NULLIF(SUM(t.cases), 0), 2) AS cfr_pct
FROM country_totals t JOIN countries c USING (country_code)
WHERE t.cases > 0
GROUP BY c.continent
ORDER BY cfr_pct DESC;

-- Q4. Global monthly trend of new cases and deaths
SELECT SUBSTR(date, 1, 7) AS month,
       CAST(SUM(new_cases) AS INTEGER)    AS new_cases,
       CAST(SUM(new_deaths) AS INTEGER)   AS new_deaths
FROM daily_stats
GROUP BY month
ORDER BY month;

-- Q5. Peak pandemic month for the 10 hardest-hit countries (window function)
WITH monthly AS (
    SELECT d.country_code, c.location, SUBSTR(d.date, 1, 7) AS month,
           SUM(d.new_cases) AS cases
    FROM daily_stats d JOIN countries c USING (country_code)
    GROUP BY d.country_code, month
),
ranked AS (
    SELECT *, RANK() OVER (PARTITION BY country_code ORDER BY cases DESC) AS rk
    FROM monthly
)
SELECT location, month, CAST(cases AS INTEGER) AS peak_monthly_cases
FROM ranked
WHERE rk = 1
ORDER BY peak_monthly_cases DESC
LIMIT 10;

-- Q6. Vaccination coverage: fully vaccinated % of population, top 15.
-- Filter tiny territories and exclude >100% artifacts (doses given to visitors).
SELECT c.location,
       ROUND(MAX(d.people_fully_vaccinated_per_hundred), 1) AS fully_vax_pct
FROM daily_stats d JOIN countries c USING (country_code)
WHERE c.population >= 1_000_000
GROUP BY d.country_code
HAVING fully_vax_pct <= 100
ORDER BY fully_vax_pct DESC
LIMIT 15;

-- Q7. When did each G20 country administer its first vaccine dose?
SELECT c.location, MIN(d.date) AS first_vax_date
FROM daily_stats d JOIN countries c USING (country_code)
WHERE d.new_vaccinations > 0
  AND c.location IN ('Argentina','Australia','Brazil','Canada','China','France',
                     'Germany','India','Indonesia','Italy','Japan','Mexico',
                     'Russia','Saudi Arabia','South Africa','South Korea',
                     'Turkey','United Kingdom','United States')
GROUP BY d.country_code
ORDER BY first_vax_date;

-- Q8. Week-over-week % change in weekly cases for India (LAG window function)
WITH weekly AS (
    SELECT strftime('%Y-%W', date) AS week, SUM(new_cases) AS cases
    FROM daily_stats WHERE country_code = 'IND'
    GROUP BY week
)
SELECT week,
       CAST(cases AS INTEGER) AS weekly_cases,
       ROUND(100.0 * (cases - LAG(cases) OVER (ORDER BY week))
             / NULLIF(LAG(cases) OVER (ORDER BY week), 0), 1) AS wow_change_pct
FROM weekly;

-- Q9. Relationship snapshot: development indicators vs outbreak severity
SELECT c.location, c.gdp_per_capita, c.life_expectancy, c.median_age,
       ROUND(MAX(d.total_cases) * 1e6 / c.population, 0)  AS cases_per_million,
       ROUND(MAX(d.total_deaths) * 1e6 / c.population, 0) AS deaths_per_million
FROM daily_stats d JOIN countries c USING (country_code)
WHERE c.population > 5_000_000
GROUP BY d.country_code
HAVING cases_per_million IS NOT NULL
ORDER BY deaths_per_million DESC
LIMIT 20;

-- Q10. Top 5 countries by cumulative cases and their share of the global total
WITH totals AS (
    SELECT country_code, MAX(total_cases) AS total_cases
    FROM daily_stats
    WHERE country_code != 'OWID_WRL'
    GROUP BY country_code
),
global AS (SELECT SUM(total_cases) AS world FROM totals),
ranked AS (
    SELECT country_code, total_cases,
           ROW_NUMBER() OVER (ORDER BY total_cases DESC) AS rn
    FROM totals
)
SELECT c.location,
       ROUND(r.total_cases/1e6, 1) AS total_cases_m,
       ROUND(100.0 * r.total_cases / NULLIF(g.world, 0), 1) AS pct_of_global
FROM ranked r JOIN countries c USING (country_code), global g
WHERE r.rn <= 5
ORDER BY r.total_cases DESC;
