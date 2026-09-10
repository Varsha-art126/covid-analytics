"""
app.py — COVID-19 Analytics dashboard (Streamlit)

Run from the project root:
    .venv/Scripts/streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "covid_analytics.db"

CONTINENT_COLORS = {
    "Africa": "#e76f51", "Asia": "#2a9d8f", "Europe": "#457b9d",
    "North America": "#e9c46a", "South America": "#9b5de5",
    "Oceania": "#f4a261",
}

st.set_page_config(page_title="COVID-19 Analytics", page_icon="🦠", layout="wide")


# --------------------------------------------------------------------------
# Data access (cached — st.cache_data hashes the sql + params, so this is safe)
# --------------------------------------------------------------------------
@st.cache_data(ttl=600)
def run_sql(sql: str, params: tuple = ()) -> pd.DataFrame:
    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)


COUNTRY_SERIES_SQL = """
    SELECT d.date, d.new_cases_smoothed, d.new_deaths_smoothed,
           d.people_fully_vaccinated_per_hundred, d.reproduction_rate,
           d.hosp_patients
    FROM daily_stats d JOIN countries c USING (country_code)
    WHERE c.location = ?
    ORDER BY d.date
"""


# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
st.sidebar.title("🦠 COVID-19 Analytics")
st.sidebar.caption("Data: Our World in Data · Jan 2020 – Aug 2024")

meta = run_sql(
    "SELECT rows_loaded, countries_loaded, min_date, max_date "
    "FROM ingestion_log ORDER BY id DESC LIMIT 1"
).iloc[0]
st.sidebar.metric("Rows in database", f"{int(meta['rows_loaded']):,}")
st.sidebar.metric("Countries", int(meta["countries_loaded"]))

page = st.sidebar.radio(
    "View",
    ["🌍 Global Overview", "📈 Country Explorer", "💉 Vaccines & Outcomes"],
)

# ==========================================================================
# Page 1 — Global Overview
# ==========================================================================
if page == "🌍 Global Overview":
    st.header("Global Overview")

    # world totals = sum of each country's peak cumulative figures
    # (world aggregate lives in `countries`, not daily_stats)
    totals = run_sql("""
        SELECT SUM(cases) AS cases, SUM(deaths) AS deaths
        FROM (SELECT country_code, MAX(total_cases) AS cases,
                     MAX(total_deaths) AS deaths
              FROM daily_stats GROUP BY country_code)
    """).iloc[0]
    world_pop = run_sql(
        "SELECT population FROM countries WHERE country_code = 'OWID_WRL'"
    ).iloc[0, 0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cases", f"{totals['cases']/1e9:.2f} B")
    c2.metric("Total deaths", f"{totals['deaths']/1e6:.1f} M")
    c3.metric("Global CFR", f"{100*totals['deaths']/totals['cases']:.2f}%")
    c4.metric("Cases per person", f"{totals['cases']/world_pop:.2f}")

    monthly = run_sql("""
        SELECT SUBSTR(date, 1, 7) AS month,
               SUM(new_cases) AS new_cases,
               SUM(new_deaths) AS new_deaths
        FROM daily_stats WHERE country_code != 'OWID_WRL'
        GROUP BY month ORDER BY month
    """)
    monthly["month_dt"] = pd.to_datetime(monthly["month"] + "-01")

    left, right = st.columns(2)
    with left:
        fig = px.area(monthly, x="month_dt", y="new_cases",
                      title="Global new cases per month",
                      labels={"month_dt": "", "new_cases": "New cases"})
        fig.update_layout(height=380)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        fig = px.area(monthly, x="month_dt", y="new_deaths",
                      title="Global new deaths per month",
                      color_discrete_sequence=["#e76f51"],
                      labels={"month_dt": "", "new_deaths": "New deaths"})
        fig.update_layout(height=380)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top 15 countries by cumulative cases")
    top = run_sql("""
        SELECT c.location, c.continent, MAX(d.total_cases) AS total_cases
        FROM daily_stats d JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL
        GROUP BY d.country_code
        ORDER BY total_cases DESC LIMIT 15
    """)
    fig = px.bar(top.sort_values("total_cases"),
                 x="total_cases", y="location", color="continent",
                 color_discrete_map=CONTINENT_COLORS, orientation="h",
                 title="Cumulative cases",
                 labels={"total_cases": "Total cases", "location": ""})
    fig.update_layout(height=520, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Severity landscape")
    cfr = run_sql("""
        WITH t AS (
            SELECT country_code, MAX(total_deaths) AS deaths,
                   MAX(total_cases) AS cases
            FROM daily_stats GROUP BY country_code
        )
        SELECT c.continent, c.location, t.cases,
               100.0 * t.deaths / NULLIF(t.cases, 0) AS cfr
        FROM t JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL AND t.cases > 100000
        ORDER BY t.cases DESC LIMIT 500
    """)
    fig = px.scatter(cfr, x="cases", y="cfr", color="continent",
                     hover_name="location", log_x=True,
                     color_discrete_map=CONTINENT_COLORS,
                     title="Case fatality ratio vs total cases (log scale)",
                     labels={"cases": "Total cases (log)", "cfr": "CFR %"})
    fig.update_layout(height=480)
    st.plotly_chart(fig, use_container_width=True)

# ==========================================================================
# Page 2 — Country Explorer
# ==========================================================================
elif page == "📈 Country Explorer":
    st.header("Country Explorer")
    countries = run_sql(
        "SELECT location FROM countries WHERE population >= 1000000 "
        "ORDER BY location"
    )["location"].tolist()
    default = countries.index("India") if "India" in countries else 0
    pick = st.multiselect("Pick countries to compare (up to 6)",
                          countries, default=[countries[default]],
                          max_selections=6)

    if not pick:
        st.info("Select at least one country.")
        st.stop()

    series = pd.concat(
        [run_sql(COUNTRY_SERIES_SQL, (c,)).assign(country=c) for c in pick]
    )
    series["date"] = pd.to_datetime(series["date"])

    metric = st.selectbox(
        "Metric",
        ["new_cases_smoothed", "new_deaths_smoothed",
         "reproduction_rate", "hosp_patients"],
        format_func={
            "new_cases_smoothed": "New cases (7-day avg)",
            "new_deaths_smoothed": "New deaths (7-day avg)",
            "reproduction_rate": "Reproduction rate R_t",
            "hosp_patients": "Hospitalized patients",
        }.get,
    )
    normed = st.toggle("Normalize to peak (compare shapes, not sizes)")

    plot_df = series[["date", "country", metric]].dropna()
    if normed and metric in plot_df:
        peak = plot_df.groupby("country")[metric].transform("max")
        plot_df[metric] = plot_df[metric] / peak

    fig = px.line(plot_df, x="date", y=metric, color="country",
                  labels={"date": "", metric: metric.replace("_", " ")})
    fig.update_layout(height=460)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Headline numbers")
    marks = ",".join("?" * len(pick))
    summary = run_sql(f"""
        SELECT c.location, c.population, c.gdp_per_capita, c.life_expectancy,
               MAX(d.total_cases) AS total_cases,
               MAX(d.total_deaths) AS total_deaths,
               MAX(d.people_fully_vaccinated_per_hundred) AS fully_vax_pct
        FROM daily_stats d JOIN countries c USING (country_code)
        WHERE c.location IN ({marks})
        GROUP BY c.location ORDER BY total_cases DESC
    """, tuple(pick))
    summary["cases_per_million"] = (summary["total_cases"]
                                    / summary["population"] * 1e6).round(0)
    st.dataframe(summary, use_container_width=True, hide_index=True)

# ==========================================================================
# Page 3 — Vaccines & Outcomes
# ==========================================================================
else:
    st.header("Vaccines & Outcomes")

    vax = run_sql("""
        SELECT c.location, c.continent, c.population,
               MAX(d.people_fully_vaccinated_per_hundred) AS fully_vax_pct
        FROM daily_stats d JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL AND c.population >= 1000000
        GROUP BY d.country_code
        HAVING fully_vax_pct <= 100
    """)
    fig = px.choropleth(vax, locations="location", locationmode="country names",
                        color="fully_vax_pct", hover_name="location",
                        color_continuous_scale="Teal",
                        title="Fully vaccinated share of population (%)")
    fig.update_layout(height=520)
    st.plotly_chart(fig, use_container_width=True)

    outcomes = run_sql("""
        WITH t AS (
            SELECT country_code, MAX(total_deaths) AS deaths
            FROM daily_stats GROUP BY country_code
        )
        SELECT c.location, c.continent, c.population, c.gdp_per_capita,
               c.median_age, c.aged_65_older, c.diabetes_prevalence,
               t.deaths * 1e6 / c.population AS deaths_per_million
        FROM t JOIN countries c USING (country_code)
        WHERE c.continent IS NOT NULL AND c.population >= 1000000
          AND t.deaths IS NOT NULL AND t.deaths > 1000
    """)

    st.subheader("What drives mortality? Deaths per million vs country traits")
    xcol = st.selectbox(
        "X-axis",
        ["gdp_per_capita", "median_age", "aged_65_older",
         "diabetes_prevalence"],
        format_func={
            "gdp_per_capita": "GDP per capita (log)",
            "median_age": "Median age",
            "aged_65_older": "Share aged 65+",
            "diabetes_prevalence": "Diabetes prevalence %",
        }.get,
    )
    fig = px.scatter(outcomes, x=xcol, y="deaths_per_million",
                     color="continent", hover_name="location",
                     trendline="ols",
                     color_discrete_map=CONTINENT_COLORS,
                     labels={"deaths_per_million": "Deaths per million"})
    if xcol == "gdp_per_capita":
        fig.update_xaxes(type="log")
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Fastest vaccine rollouts (fully vaccinated %, top 15)")
    top_vax = vax.sort_values("fully_vax_pct", ascending=False).head(15)
    fig = px.bar(top_vax.sort_values("fully_vax_pct"),
                 x="fully_vax_pct", y="location", color="continent",
                 color_discrete_map=CONTINENT_COLORS, orientation="h",
                 labels={"fully_vax_pct": "Fully vaccinated %", "location": ""})
    fig.update_layout(height=480, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

st.sidebar.divider()
st.sidebar.caption("Built with Python · SQLite · pandas · Plotly · Streamlit")
