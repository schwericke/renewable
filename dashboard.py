"""
Germany Renewable Energy Dashboard
Real-time view of renewable electricity in Germany
"""

import streamlit as st
import os
import requests
import json
import time
import xml.etree.ElementTree as ET
import holidays
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Germany Renewable Energy", layout="wide")


# =============================================================================
# Fetch renewable generation from ENTSOE
# =============================================================================

@st.cache_data(ttl=3600)
def get_entsoe_data(date_str):
    """Get renewable energy generation for a specific day"""

    api_key = os.getenv("ENTSOE_API_KEY")

    params = {
        "securityToken": api_key,
        "documentType": "A75",
        "processType": "A16",
        "in_Domain": "10Y1001A1001A83F",
        "out_Domain": "10Y1001A1001A83F",
        "periodStart": f"{date_str}0000",
        "periodEnd": f"{date_str}2359",
    }

    # Retry up to 3 times if timeout
    for attempt in range(3):
        try:
            response = requests.get("https://web-api.tp.entsoe.eu/api", params=params, timeout=120)
            response.raise_for_status()
            break
        except requests.exceptions.Timeout:
            if attempt == 2:  # Last attempt
                raise
            time.sleep(2)  # Wait before retry

    xml_data = ET.fromstring(response.content)
    namespace = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}

    # Renewable sources: biomass, hydro, solar, wind, etc.
    renewables = ["B01", "B09", "B11", "B12", "B15", "B16", "B17", "B18", "B19"]

    # Collect all 15-min MW values (ordered by position)
    # Position 1 = 00:00, Position 2 = 00:15, etc.
    all_values = []
    day_start = datetime.strptime(date_str, "%Y%m%d")

    for time_series in xml_data.findall(".//ns:TimeSeries", namespace):
        energy_type = time_series.find(".//ns:psrType", namespace)

        if energy_type is not None and energy_type.text in renewables:
            period = time_series.find(".//ns:Period", namespace)
            if period is not None:
                for data_point in period.findall(".//ns:Point", namespace):
                    power_value = float(data_point.find("ns:quantity", namespace).text)
                    position = int(data_point.find("ns:position", namespace).text)
                    # Calculate timestamp
                    timestamp = day_start + timedelta(minutes=15 * (position - 1))
                    all_values.append((timestamp, power_value))

    # Sort by timestamp
    all_values.sort()
    last_time = all_values[-1][0] if all_values else datetime.now()

    return {
        "data_points": all_values,  # List of (timestamp, MW)
        "last_datapoint": last_time
    }


@st.cache_data(ttl=3600)
def get_smard_data(date_str):
    """Get electricity consumption for a specific day"""

    day = datetime.strptime(date_str, "%Y%m%d")

    # Get latest available data block
    index_url = "https://www.smard.de/app/chart_data/410/DE/index_hour.json"
    timestamps = requests.get(index_url, timeout=30).json()["timestamps"]
    latest = timestamps[-1]

    # Fetch consumption data
    url = f"https://www.smard.de/app/chart_data/410/DE/410_DE_hour_{latest}.json"
    data = requests.get(url, timeout=30).json()["series"]

    # Filter to today (SMARD uses millisecond timestamps)
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = int(midnight.timestamp() * 1000)
    end_ms = start_ms + (24 * 3600 * 1000)

    points = []
    for timestamp_ms, value in data:
        if start_ms <= timestamp_ms < end_ms and value is not None:
            time = datetime.fromtimestamp(timestamp_ms / 1000)
            points.append((time, value))  # (timestamp, MWh)

    points.sort()
    last_time = points[-1][0] if points else datetime.now()

    return {
        "data_points": points,  # List of (timestamp, MWh)
        "last_datapoint": last_time
    }


# =============================================================================
# Fetch weather conditions from Open-Meteo
# =============================================================================

@st.cache_data(ttl=3600)
def get_weather_data(date_str):
    """Get average weather across Germany for a specific day"""

    # Five cities representing different parts of Germany
    cities = {
        "Hamburg": (53.55, 10.00),
        "Berlin": (52.52, 13.40),
        "Frankfurt": (50.11, 8.68),
        "Munich": (48.14, 11.58),
        "Freiburg": (47.99, 7.85),
    }

    sun_hours_list = []
    wind_speeds_list = []

    for city, (lat, lon) in cities.items():
        url = (f"https://api.open-meteo.com/v1/forecast?"
               f"latitude={lat}&longitude={lon}"
               f"&daily=sunshine_duration,wind_speed_10m_max"
               f"&timezone=Europe/Berlin"
               f"&start_date={date_str}&end_date={date_str}")

        result = requests.get(url).json()

        if "daily" in result:
            sun_hours_list.append(result["daily"]["sunshine_duration"][0] / 3600)
            wind_speeds_list.append(result["daily"]["wind_speed_10m_max"][0])

    return {
        "sun_hours": sum(sun_hours_list) / len(sun_hours_list),
        "wind_speed": sum(wind_speeds_list) / len(wind_speeds_list)
    }


# =============================================================================
# Page styling
# =============================================================================

st.markdown("""
<style>
    * { font-family: 'Times New Roman', Times, serif !important; }
    .main .block-container { text-align: center; }
    h1, h2, h3 { text-align: center; }
    .tiny-button { margin: 0; padding: 0; }
    .tiny-button button {
        font-size: 9px; padding: 0; height: 16px; width: 20px;
        background-color: transparent; border: 1px solid #d1d5db;
        color: #6b7280; cursor: pointer;
    }
    .tiny-button button:hover { background-color: #f3f4f6; }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Header
# =============================================================================

st.title("⚡️ Renewables 🇩🇪")
st.markdown("<p style='text-align: center; margin-top: -20px;'>(% of consumption)</p>",
            unsafe_allow_html=True)

_left, divider, _right = st.columns([1, 4, 1])
with divider:
    st.divider()


# =============================================================================
# Load today's data
# =============================================================================

today = datetime.now()
today_str = today.strftime("%Y-%m-%d")
today_date_str = today.strftime("%Y%m%d")

# Fetch data (all cached for 1 hour)
generation_data = get_entsoe_data(today_date_str)
consumption_data = get_smard_data(today_date_str)
weather = get_weather_data(today_str)

# Find bottleneck (earliest timestamp where we have BOTH datasets)
gen_last = generation_data["last_datapoint"]
cons_last = consumption_data["last_datapoint"]
bottleneck = min(gen_last, cons_last)

# Filter both datasets to only use overlapping time period
gen_points = [(t, mw) for t, mw in generation_data["data_points"] if t <= bottleneck]
cons_points = [(t, mwh) for t, mwh in consumption_data["data_points"] if t <= bottleneck]

# Calculate totals
renewable_MWh = sum([mw * 0.25 for _, mw in gen_points])  # Convert MW to MWh
consumption_MWh = sum([mwh for _, mwh in cons_points])
todays_renewable_share = (renewable_MWh / consumption_MWh * 100) if consumption_MWh > 0 else 0
last_data_time = bottleneck

# Check if today is a holiday
berlin_holidays = holidays.Germany(prov="BE", years=today.year)
is_holiday = today.date() in berlin_holidays


# =============================================================================
# Compare to yearly averages
# =============================================================================

YEARLY_AVG_FILE = "yearly_avg.json"
current_year = today.year

# Load this year's average
if os.path.exists(YEARLY_AVG_FILE):
    with open(YEARLY_AVG_FILE) as f:
        data = json.load(f)
        yearly_renewable_avg = data["renewable_share"] if data.get("year") == current_year else 57.4
else:
    yearly_renewable_avg = 57.4

# Typical German weather
yearly_sun_avg = 4.7    # hours per day
yearly_wind_avg = 12.5  # km/h

# Today vs average
renewable_diff = todays_renewable_share - yearly_renewable_avg
sun_diff = weather["sun_hours"] - yearly_sun_avg
wind_diff = weather["wind_speed"] - yearly_wind_avg

# Colored arrows (green = good, red = bad)
def arrow(diff):
    return "<span style='color: #00674F;'>↑</span>" if diff > 0 else "<span style='color: #DC2626;'>↓</span>"

renewable_arrow = arrow(renewable_diff)
sun_arrow = arrow(sun_diff)
wind_arrow = arrow(wind_diff)


# =============================================================================
# Today section
# =============================================================================

st.markdown("<h2 style='text-align: center;'>Today</h2>", unsafe_allow_html=True)

left_col, right_col = st.columns([1, 1])

# Show today's percentage
with left_col:
    st.markdown(f"""
    <div style='display: flex; justify-content: flex-end;'>
        <div style='text-align: center;'>
            <h1 style='font-size: 80px; margin: 0; margin-top: -30px;'>{todays_renewable_share:.1f}%</h1>
            <p style='margin: 0; margin-top: -10px;'><i>{renewable_arrow} {abs(renewable_diff):.1f}% {'above' if renewable_diff > 0 else 'below'} avg</i></p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Show weather and day type
with right_col:
    st.markdown(f"<div style='text-align: left;'>"
                f"☀️ Sun {weather['sun_hours']:.1f} h  {sun_arrow} {abs(sun_diff):.1f} h {'above' if sun_diff > 0 else 'below'} avg"
                f"</div>", unsafe_allow_html=True)

    st.markdown(f"<div style='text-align: left; margin-top: 20px;'>"
                f"💨 Wind {weather['wind_speed']:.1f} km/h  {wind_arrow} {abs(wind_diff):.1f} km/h {'above' if wind_diff > 0 else 'below'} avg"
                f"</div>", unsafe_allow_html=True)

    # Day type (affects electricity demand)
    is_weekend = today.weekday() >= 5
    if is_holiday:
        day_type, day_arrow, demand = "Holiday", "↑", "lower demand"
    elif is_weekend:
        day_type, day_arrow, demand = "Weekend", "↑", "lower demand"
    else:
        day_type, day_arrow, demand = "Working Day", "↓", "higher demand"

    arrow_color = "#00674F" if day_arrow == "↑" else "#DC2626"
    st.markdown(f"<div style='text-align: left; margin-top: 20px;'>"
                f"📅 {day_type} <span style='color: {arrow_color};'>{day_arrow}</span> {demand}"
                f"</div>", unsafe_allow_html=True)


# =============================================================================
# Historical progress
# =============================================================================

st.markdown("<br><br>", unsafe_allow_html=True)

# Load this year's average
this_year_avg = yearly_renewable_avg  # Already loaded above

# Progress toward 2030 target
target_2030 = 80.0
years_left = 2030 - current_year
label_pos = (this_year_avg + target_2030) / 2

# Progress bar row
_left, bar_area, _right = st.columns([1, 4, 1])

with bar_area:
    # Two-color progress bar (green = achieved, yellow = remaining)
    st.markdown(f"""
    <div style="width: 100%; height: 30px; background-color: #e5e7eb; border-radius: 5px; overflow: hidden; position: relative;">
        <div style="width: {this_year_avg}%; height: 100%; background-color: #00674F; float: left;"></div>
        <div style="width: {target_2030 - this_year_avg}%; height: 100%; background-color: #EFCF50; float: left;"></div>
        <div style="position: absolute; left: 0%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 6%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 20%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 50%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: {this_year_avg}%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; left: 80%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
        <div style="position: absolute; right: 0%; top: 0; width: 1px; height: 30px; background-color: #000000;"></div>
    </div>
    """, unsafe_allow_html=True)

# Timeline labels
_left2, labels_area, _right2 = st.columns([1, 4, 1])
with labels_area:
    st.markdown(f"""
    <div style="position: relative; width: 100%; height: 80px; margin-top: 5px;">
        <span style="position: absolute; left: 0%; transform: translateX(-50%); text-align: center;"><b>0%</b></span>
        <span style="position: absolute; left: 6%; transform: translateX(-50%); text-align: center;"><b>6%</b><br>2000</span>
        <span style="position: absolute; left: 20%; transform: translateX(-50%); text-align: center;"><b>20%</b><br>2010</span>
        <span style="position: absolute; left: 50%; transform: translateX(-50%); text-align: center;"><b>50%</b><br>2020</span>
        <span style="position: absolute; left: {this_year_avg}%; transform: translateX(-50%); text-align: center;"><b>{this_year_avg:.1f}%</b><br>{current_year}<br><b style="font-size: 36px; color: #00674F;">⬆</b></span>
        <span style="position: absolute; left: {label_pos}%; transform: translateX(-50%); text-align: center; color: #EFCF50;">{years_left} years to reach target</span>
        <span style="position: absolute; left: 80%; transform: translateX(-50%); text-align: center;"><b>80%</b><br>2030<br><span style="color: #EFCF50;">EEG Target</span></span>
        <span style="position: absolute; right: 0%; transform: translateX(50%); text-align: center;"><b>100%</b></span>
    </div>
    """, unsafe_allow_html=True)


# =============================================================================
# Footer
# =============================================================================

_left3, divider2, _right3 = st.columns([1, 4, 1])
with divider2:
    st.divider()

# Show last available data timestamp
last_data_str = last_data_time.strftime("%H:%M, %B %d, %Y")
st.markdown(f"<p style='text-align: center; margin-bottom: 5px;'><i>🕒 Last available data: {last_data_str}</i></p>",
            unsafe_allow_html=True)

# Sources and update button
sources_left, sources_center, button_right = st.columns([1, 4, 1])

with sources_center:
    st.markdown("<p style='text-align: center; font-size: 12px; color: #6b7280; margin-top: 0px;'>"
                "Sources: ENTSO-E (generation) · SMARD (consumption) · Open-Meteo (weather)</p>",
                unsafe_allow_html=True)

with button_right:
    st.markdown('<div class="tiny-button">', unsafe_allow_html=True)
    if st.button("🔄 Update", key="update_avg"):
        with st.spinner("Updating..."):
            try:
                # Update yearly average using incremental caching
                cutoff = today - timedelta(days=14)
                cutoff_str = cutoff.strftime("%Y%m%d")

                # Load cached finalized data
                finalized_renewable = 0
                finalized_consumption = 0
                last_finalized = None
                cached_avg = None

                if os.path.exists(YEARLY_AVG_FILE):
                    with open(YEARLY_AVG_FILE) as f:
                        cache = json.load(f)
                        if cache.get("year") == current_year and "finalized_date" in cache:
                            finalized_renewable = cache.get("finalized_renewable_MWh", 0)
                            finalized_consumption = cache.get("finalized_consumption_MWh", 0)
                            last_finalized = cache["finalized_date"]
                            cached_avg = cache.get("renewable_share")

                # If nothing new to finalize, just reload
                if last_finalized == cutoff_str and cached_avg:
                    st.rerun()

                # Determine what to fetch
                if last_finalized is None:
                    # First time: get everything from Jan 1 to cutoff
                    fetch_start = f"{current_year}0101"
                else:
                    # Subsequent: only get days after last finalized (no double-counting)
                    next_day = datetime.strptime(last_finalized, "%Y%m%d") + timedelta(days=1)
                    fetch_start = next_day.strftime("%Y%m%d")

                # Fetch newly finalized generation (ENTSOE)
                api_key = os.getenv("ENTSOE_API_KEY")
                namespace = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}
                renewables = ["B01", "B09", "B11", "B12", "B15", "B16", "B17", "B18", "B19"]

                params = {
                    "securityToken": api_key,
                    "documentType": "A75",
                    "processType": "A16",
                    "in_Domain": "10Y1001A1001A83F",
                    "out_Domain": "10Y1001A1001A83F",
                    "periodStart": f"{fetch_start}0000",
                    "periodEnd": f"{cutoff_str}2359",
                }

                response = requests.get("https://web-api.tp.entsoe.eu/api", params=params, timeout=120)
                response.raise_for_status()
                xml_data = ET.fromstring(response.content)

                new_renewable = 0
                for series in xml_data.findall(".//ns:TimeSeries", namespace):
                    energy_type = series.find(".//ns:psrType", namespace)
                    if energy_type and energy_type.text in renewables:
                        period = series.find(".//ns:Period", namespace)
                        if period:
                            for point in period.findall(".//ns:Point", namespace):
                                new_renewable += float(point.find("ns:quantity", namespace).text) * 0.25

                finalized_renewable += new_renewable

                # Fetch newly finalized consumption (SMARD)
                index_url = "https://www.smard.de/app/chart_data/410/DE/index_hour.json"
                all_timestamps = requests.get(index_url, timeout=30).json()["timestamps"]

                start_ms = int(datetime.strptime(fetch_start, "%Y%m%d").timestamp() * 1000)
                cutoff_ms = int(cutoff.timestamp() * 1000)

                # Only fetch SMARD blocks that might contain our date range
                for ts in all_timestamps:
                    if datetime.fromtimestamp(ts/1000).year != current_year:
                        continue
                    block_end = ts + (7 * 24 * 3600 * 1000)  # 7-day blocks
                    if ts > cutoff_ms or block_end < start_ms:
                        continue

                    url = f"https://www.smard.de/app/chart_data/410/DE/410_DE_hour_{ts}.json"
                    data = requests.get(url, timeout=30).json()["series"]
                    for timestamp, value in data:
                        if start_ms <= timestamp < cutoff_ms and value:
                            finalized_consumption += value

                time.sleep(5)  # Small delay before next request

                # Fetch last 13 days (rolling window, day after cutoff to today)
                recent_start = cutoff + timedelta(days=1)
                recent_start_str = recent_start.strftime("%Y%m%d")

                params["periodStart"] = f"{recent_start_str}0000"
                params["periodEnd"] = today.strftime("%Y%m%d2359")

                response = requests.get("https://web-api.tp.entsoe.eu/api", params=params, timeout=120)
                response.raise_for_status()
                xml_data = ET.fromstring(response.content)

                recent_renewable = 0
                for series in xml_data.findall(".//ns:TimeSeries", namespace):
                    energy_type = series.find(".//ns:psrType", namespace)
                    if energy_type and energy_type.text in renewables:
                        period = series.find(".//ns:Period", namespace)
                        if period:
                            for point in period.findall(".//ns:Point", namespace):
                                recent_renewable += float(point.find("ns:quantity", namespace).text) * 0.25

                # SMARD consumption for last 13 days
                latest_ts = requests.get(index_url, timeout=30).json()["timestamps"][-1]
                url = f"https://www.smard.de/app/chart_data/410/DE/410_DE_hour_{latest_ts}.json"
                data = requests.get(url, timeout=30).json()["series"]

                recent_start_ms = int(recent_start.timestamp() * 1000)
                recent_consumption = sum([v for t, v in data if t >= recent_start_ms and v])

                # Calculate new average
                total_renewable = finalized_renewable + recent_renewable
                total_consumption = finalized_consumption + recent_consumption
                new_avg = (total_renewable / total_consumption * 100) if total_consumption > 0 else 0

                # Don't save if the result is suspiciously low (API error likely)
                if new_avg < 10:
                    st.error("Update failed. Data incomplete.")
                    st.stop()

                # Save updated finalized data
                with open(YEARLY_AVG_FILE, "w") as f:
                    json.dump({
                        "year": current_year,
                        "renewable_share": new_avg,
                        "finalized_date": cutoff_str,
                        "finalized_renewable_MWh": finalized_renewable,
                        "finalized_consumption_MWh": finalized_consumption
                    }, f)

                # Clear today's cache and reload
                get_entsoe_data.clear()
                get_smard_data.clear()
                st.rerun()
                
            except Exception as e:
                st.error(f"Update failed: {str(e)}")
                st.stop()
    st.markdown('</div>', unsafe_allow_html=True)  # Close tiny-button div
