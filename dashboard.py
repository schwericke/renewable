#!/usr/bin/env python3
"""
Germany Renewable Energy Dashboard
Shows today's renewable electricity share with weather conditions and historical progress
"""

import streamlit as st
import os
import requests
import xml.etree.ElementTree as ET
import holidays
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables (ENTSOE API key)
load_dotenv()

# Configure Streamlit page
st.set_page_config(page_title="Germany Renewable Energy", layout="wide")


# ============================================================================
# DATA FETCHING: Get today's renewable energy data
# ============================================================================

@st.cache_data(ttl=3600)  # Cache for 1 hour to avoid repeated API calls
def get_renewable_data():
    """
    Fetch today's renewable electricity share for Germany

    Returns:
        dict: Contains renewable_share (%), last_datapoint time, and energy amounts
    """
    # Setup: Get API key and today's date
    api_key = os.getenv("ENTSOE_API_KEY")
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")

    # -------------------------------------------------------------------------
    # STEP 1: Get renewable PRODUCTION from ENTSOE
    # -------------------------------------------------------------------------
    # ENTSOE provides detailed generation data by energy type (15-min intervals)

    request_params = {
        "securityToken": api_key,
        "documentType": "A75",      # Actual generation per type
        "processType": "A16",        # Realized
        "in_Domain": "10Y1001A1001A83F",   # Germany
        "out_Domain": "10Y1001A1001A83F",  # Germany
        "periodStart": f"{today_str}0000",
        "periodEnd": f"{today_str}2359",
    }

    response = requests.get("https://web-api.tp.entsoe.eu/api", params=request_params)
    xml_data = ET.fromstring(response.content)
    xml_namespace = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}

    # Renewable energy types (ENTSOE codes)
    # B01=Biomass, B09=Geothermal, B11=Hydro, B12=Marine, B15=Other renewable
    # B16=Solar, B17=Waste, B18=Wind offshore, B19=Wind onshore
    renewable_types = ["B01", "B09", "B11", "B12", "B15", "B16", "B17", "B18", "B19"]

    # Sum up all renewable production (in MW, 15-minute intervals)
    total_renewable_MW = 0
    for time_series in xml_data.findall(".//ns:TimeSeries", xml_namespace):
        energy_type = time_series.find(".//ns:psrType", xml_namespace)

        if energy_type is not None and energy_type.text in renewable_types:
            period = time_series.find(".//ns:Period", xml_namespace)
            if period is not None:
                for data_point in period.findall(".//ns:Point", xml_namespace):
                    power_value = float(data_point.find("ns:quantity", xml_namespace).text)
                    total_renewable_MW += power_value

    # Convert from MW (15-min intervals) to MWh (multiply by 0.25 hours)
    total_renewable_MWh = total_renewable_MW * 0.25

    # -------------------------------------------------------------------------
    # STEP 2: Get total CONSUMPTION from SMARD
    # -------------------------------------------------------------------------
    # SMARD provides Germany's total electricity consumption (hourly data)

    # Find the most recent data block available
    smard_index_url = "https://www.smard.de/app/chart_data/410/DE/index_hour.json"
    available_timestamps = requests.get(smard_index_url).json()["timestamps"]
    most_recent_timestamp = available_timestamps[-1]

    # Calculate today's time range in milliseconds (SMARD uses Unix time * 1000)
    midnight_today = today.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_ms = int(midnight_today.timestamp() * 1000)
    today_end_ms = today_start_ms + (24 * 3600 * 1000)  # Add 24 hours

    # Fetch consumption data for today
    consumption_url = f"https://www.smard.de/app/chart_data/410/DE/410_DE_hour_{most_recent_timestamp}.json"
    all_consumption = requests.get(consumption_url).json()["series"]

    # Filter to only today's data points
    todays_consumption = [
        point for point in all_consumption
        if today_start_ms <= point[0] < today_end_ms and point[1] is not None
    ]

    # Sum up total consumption for today
    total_consumption_MWh = sum([point[1] for point in todays_consumption])

    # Find when the last data was recorded
    if todays_consumption:
        last_point_timestamp = todays_consumption[-1][0]
        last_data_time = datetime.fromtimestamp(last_point_timestamp / 1000)
    else:
        last_data_time = datetime.now()

    # -------------------------------------------------------------------------
    # STEP 3: Calculate renewable share
    # -------------------------------------------------------------------------
    # Renewable share = (renewable production / total consumption) * 100

    if total_consumption_MWh > 0:
        renewable_percentage = (total_renewable_MWh / total_consumption_MWh * 100)
    else:
        renewable_percentage = 0

    return {
        "renewable_share": renewable_percentage,
        "last_datapoint": last_data_time,
        "renewable_MWh": total_renewable_MWh,
        "consumption_MWh": total_consumption_MWh
    }


# ============================================================================
# WEATHER DATA: Get today's weather conditions
# ============================================================================

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_weather_data():
    """
    Fetch today's weather conditions for Germany
    Averages data from 5 representative cities across the country

    Returns:
        dict: Contains sun_hours, wind_speed, and is_holiday flag
    """
    # Representative cities covering different regions of Germany
    german_cities = {
        "Hamburg": (53.55, 10.00),      # North
        "Berlin": (52.52, 13.40),        # East
        "Frankfurt": (50.11, 8.68),      # Center
        "Munich": (48.14, 11.58),        # South
        "Freiburg": (47.99, 7.85),       # Southwest
    }

    today_str = datetime.now().strftime("%Y-%m-%d")
    sunshine_hours = []
    wind_speeds = []

    # Fetch weather data from Open-Meteo for each city
    for city_name, (latitude, longitude) in german_cities.items():
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={latitude}&longitude={longitude}"
            f"&daily=sunshine_duration,wind_speed_10m_max"
            f"&timezone=Europe/Berlin"
            f"&start_date={today_str}&end_date={today_str}"
        )

        weather_data = requests.get(weather_url).json()

        if "daily" in weather_data:
            # Convert sunshine from seconds to hours
            sunshine_hours.append(weather_data["daily"]["sunshine_duration"][0] / 3600)
            wind_speeds.append(weather_data["daily"]["wind_speed_10m_max"][0])

    # Calculate Germany-wide averages
    avg_sunshine = sum(sunshine_hours) / len(sunshine_hours)
    avg_wind = sum(wind_speeds) / len(wind_speeds)

    # Check if today is a holiday in Berlin
    today = datetime.now().date()
    berlin_holidays = holidays.Germany(prov="BE", years=today.year)
    is_holiday = today in berlin_holidays

    return {
        "sun_hours": avg_sunshine,
        "wind_speed": avg_wind,
        "is_holiday": is_holiday
    }


# ============================================================================
# PAGE STYLING: Times New Roman font for professional look
# ============================================================================

st.markdown("""
<style>
    * {
        font-family: 'Times New Roman', Times, serif !important;
    }
    .main .block-container {
        text-align: center;
    }
    h1, h2, h3 {
        text-align: center;
        font-family: 'Times New Roman', Times, serif !important;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# HEADER: Title and subtitle
# ============================================================================

st.title("⚡️ Renewable share 🇩🇪")
st.markdown(
    "<p style='text-align: center; margin-top: -20px;'>"
    "How much of Germany's electricity comes from renewable sources"
    "</p>",
    unsafe_allow_html=True
)


# ============================================================================
# DIVIDER
# ============================================================================

# Create centered divider (occupies middle 2/3 of page width)
_left, divider, _right = st.columns([1, 4, 1])
with divider:
    st.divider()


# ============================================================================
# LOAD DATA: Fetch today's renewable share and weather conditions
# ============================================================================

# Get weather conditions (cached for 1 hour)
weather = get_weather_data()
todays_sun_hours = weather["sun_hours"]
todays_wind_speed = weather["wind_speed"]
todays_is_holiday = weather["is_holiday"]

# Get renewable energy data (cached for 1 hour)
energy = get_renewable_data()
todays_renewable_share = energy["renewable_share"]
last_data_time = energy["last_datapoint"]


# ============================================================================
# COMPARISONS: Calculate differences from yearly averages
# ============================================================================

# Germany's typical yearly averages
YEARLY_AVG_RENEWABLE = 57.4    # % renewable electricity share
YEARLY_AVG_SUN = 4.7           # hours of sunshine per day
YEARLY_AVG_WIND = 12.5         # km/h average wind speed

# How does today compare?
renewable_diff = todays_renewable_share - YEARLY_AVG_RENEWABLE
sun_diff = todays_sun_hours - YEARLY_AVG_SUN
wind_diff = todays_wind_speed - YEARLY_AVG_WIND

# Create colored arrows: green ↑ for above average, red ↓ for below
def make_arrow(difference):
    if difference > 0:
        return "<span style='color: #00674F;'>↑</span>"  # Green up
    else:
        return "<span style='color: #DC2626;'>↓</span>"  # Red down

renewable_arrow = make_arrow(renewable_diff)
sun_arrow = make_arrow(sun_diff)
wind_arrow = make_arrow(wind_diff)


# ============================================================================
# TODAY SECTION: Show today's renewable share with weather predictors
# ============================================================================

st.markdown("<h2 style='text-align: center;'>Today</h2>", unsafe_allow_html=True)

# Display in two equal columns
percentage_column, predictors_column = st.columns([1, 1])

# LEFT COLUMN: Today's renewable percentage
with percentage_column:
    st.markdown(f"""
    <div style='display: flex; justify-content: flex-end;'>
        <div style='text-align: center;'>
            <h1 style='font-size: 80px; margin: 0; margin-top: -30px;'>{todays_renewable_share:.1f}%</h1>
            <p style='margin: 0; margin-top: -10px;'><i>{renewable_arrow} {abs(renewable_diff):.1f}% from usual</i></p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# RIGHT COLUMN: Weather conditions that affect renewable production
with predictors_column:
    # Sunshine affects solar panel output
    st.markdown(
        f"<div style='text-align: left;'>"
        f"☀️ Sun {todays_sun_hours:.1f} h  {sun_arrow} {abs(sun_diff):.1f} h from usual"
        f"</div>",
        unsafe_allow_html=True
    )

    # Wind affects wind turbine output
    st.markdown(
        f"<div style='text-align: left; margin-top: 20px;'>"
        f"💨 Wind {todays_wind_speed:.1f} km/h  {wind_arrow} {abs(wind_diff):.1f} km/h from usual"
        f"</div>",
        unsafe_allow_html=True
    )

    # Day type affects total demand (weekends/holidays = less industry)
    today = datetime.now()
    is_weekend = today.weekday() >= 5  # Saturday=5, Sunday=6

    if is_weekend:
        day_label = "Weekend"
        day_arrow = "<span style='color: #00674F;'>↑</span>"  # Green up (good for renewable %)
        demand_note = "lower demand"
    elif todays_is_holiday:
        day_label = "Holiday"
        day_arrow = "<span style='color: #00674F;'>↑</span>"  # Green up
        demand_note = "lower demand"
    else:
        day_label = "Working Day"
        day_arrow = "<span style='color: #DC2626;'>↓</span>"  # Red down (harder to meet demand)
        demand_note = "higher demand"

    st.markdown(
        f"<div style='text-align: left; margin-top: 20px;'>"
        f"📅 {day_label} {day_arrow} {demand_note}"
        f"</div>",
        unsafe_allow_html=True
    )


# ============================================================================
# SPACING before historical progress bar
# ============================================================================

st.markdown("<br><br>", unsafe_allow_html=True)


# ============================================================================
# HISTORICAL PROGRESS: Show Germany's renewable journey from 2000 to 2030
# ============================================================================

# Get this year's average (use saved value or default)
current_year = datetime.now().year
this_years_average = 57.4  # Default value

# Try to load from saved history if available
import json
if os.path.exists("renewable_history.json"):
    with open("renewable_history.json") as history_file:
        history = json.load(history_file)
        if str(current_year) in history:
            saved_value = history[str(current_year)]["renewable_share_percent"]
            if saved_value:
                this_years_average = saved_value

# Germany's 2030 target from EEG (Renewable Energy Act)
TARGET_2030 = 80.0
years_remaining = 2030 - current_year

# Create centered layout (progress bar in middle 2/3 of page)
_left, progress_bar_area, _right = st.columns([1, 4, 1])

with progress_bar_area:
    # Calculate position for "years remaining" label (midpoint between now and 2030)
    label_position = (this_years_average + TARGET_2030) / 2

    # PROGRESS BAR: Two-color bar showing achieved (green) vs remaining (yellow)
    st.markdown(f"""
    <div style="width: 100%; height: 30px; background-color: #e5e7eb; border-radius: 5px; overflow: hidden; position: relative;">
        <div style="width: {this_years_average}%; height: 100%; background-color: #00674F; float: left;"></div>
        <div style="width: {TARGET_2030 - this_years_average}%; height: 100%; background-color: #EFCF50; float: left;"></div>
        <div style="position: absolute; left: 0%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 6%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 20%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 50%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: {this_years_average}%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 80%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; right: 0%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
    </div>
    """, unsafe_allow_html=True)

    # TIMELINE LABELS: Show historical milestones and target
    st.markdown(f"""
    <div style="position: relative; width: 100%; height: 80px; margin-top: 5px; font-family: 'Times New Roman', Times, serif;">
        <span style="position: absolute; left: 0%; transform: translateX(-50%); text-align: center;"><b>0%</b></span>
        <span style="position: absolute; left: 6%; transform: translateX(-50%); text-align: center;"><b>6%</b><br>2000</span>
        <span style="position: absolute; left: 20%; transform: translateX(-50%); text-align: center;"><b>20%</b><br>2010</span>
        <span style="position: absolute; left: 50%; transform: translateX(-50%); text-align: center;"><b>50%</b><br>2020</span>
        <span style="position: absolute; left: {this_years_average}%; transform: translateX(-50%); text-align: center;"><b>{this_years_average:.1f}%</b><br>{current_year}<br><b style="font-size: 36px; color: #00674F;">⬆</b></span>
        <span style="position: absolute; left: {label_position}%; transform: translateX(-50%); text-align: center; color: #EFCF50;">{years_remaining} years to reach target</span>
        <span style="position: absolute; left: 80%; transform: translateX(-50%); text-align: center;"><b>80%</b><br>2030<br><span style="color: #EFCF50;">EEG Target</span></span>
        <span style="position: absolute; right: 0%; transform: translateX(50%); text-align: center;"><b>100%</b></span>
    </div>
    """, unsafe_allow_html=True)


# ============================================================================
# FOOTER: Data timestamp and sources
# ============================================================================

# Another centered divider
_left2, divider2, _right2 = st.columns([1, 4, 1])
with divider2:
    st.divider()

# Show when data was last updated
last_data_str = last_data_time.strftime("%H:%M, %B %d, %Y")
st.markdown(
    f"<p style='text-align: center; margin-bottom: 5px;'>"
    f"<i>🕒 Last available data: {last_data_str}</i>"
    f"</p>",
    unsafe_allow_html=True
)

# Credit data sources
st.markdown(
    "<p style='text-align: center; font-size: 12px; color: #6b7280; margin-top: 0;'>"
    "Sources: ENTSO-E (generation) · SMARD (consumption) · Open-Meteo (weather)"
    "</p>",
    unsafe_allow_html=True
)
