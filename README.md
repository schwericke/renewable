# ⚡️ Germany Renewable Energy Dashboard

A real-time dashboard showing Germany's renewable electricity share with weather conditions and historical progress toward the 2030 renewable energy target.

## Features

- **Today's Renewable Share**: Live percentage of electricity from renewable sources
- **Weather Conditions**: Sun hours and wind speed affecting renewable generation
- **Historical Progress**: Visual timeline from 2000 to 2030 EEG target (80%)
- **Smart Caching**: Efficient data fetching with 1-hour cache
- **Incremental Updates**: Fast yearly average updates (only fetches new data)

## Data Sources

- **ENTSO-E**: Renewable generation data (15-minute intervals)
- **SMARD**: Electricity consumption data (hourly)
- **Open-Meteo**: Weather data (daily forecasts)

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create `.env` file with your ENTSOE API key:
```
ENTSOE_API_KEY=your_key_here
```

3. Run the dashboard:
```bash
streamlit run dashboard.py
```

## Usage

- Dashboard auto-refreshes data every hour
- Click **🔄 Update** button to:
  - Refresh today's renewable share
  - Update this year's average
  - Fetch latest available data

## Cache System

- **Today's data**: Cached for 1 hour
- **Weather**: Cached in session state
- **Yearly average**: Incremental updates (only fetches last 2 weeks + new data)

## Technical Details

**Bottleneck Filtering**: Only uses data where BOTH generation and consumption are available, ensuring accurate calculations.

**Incremental Updates**: The yearly average is calculated by:
1. Storing finalized data (older than 2 weeks)
2. Only fetching recent data on updates
3. Subsequent daily updates take ~10 seconds instead of minutes
