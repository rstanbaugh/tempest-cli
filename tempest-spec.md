---
spec:
  id: tempest-cli
  title: Tempest (WeatherFlow) CLI Program Specification
  status: active
  version: 1.0.0
  last_updated: 2026-03-04
  implementation_target: /Users/rstanbaugh/.openclaw/tools/tempest/tempest-cli.py
  language: python3
  owner: rstanbaugh
runtime:
  executable: tempest-cli
  python_min_version: "3.9"
  dependencies:
    - requests
    - python-dotenv (optional)
api:
  endpoint: https://swd.weatherflow.com/swd/rest/better_forecast
  query_units:
    units_temp: f
    units_wind: mph
    units_pressure: inhg
    units_precip: in
    units_distance: mi
configuration:
  required_env:
    - TEMPEST_API_KEY
    - TEMPEST_STATION_ID
  optional_env:
    TEMPEST_TIMEOUT_S:
      type: float
      default: 8
  dotenv_fallback: ~/.openclaw/.env
---

# Tempest CLI Program Specification

## 1) Purpose
Provide a single-command CLI to fetch and render **current conditions** and **forecast** data from a Tempest station, with:
- human-readable text output (default and raw)
- raw JSON output for machine inspection
- deterministic unit formatting and timestamp handling

## 2) Command Interface

```yaml
commands:
  current:
    usage: tempest-cli current [--raw|--json] [--timeout <seconds>]
    behavior:
      - fetches better_forecast once
      - renders current conditions section
  forecast:
    usage: tempest-cli forecast [--daily|--hourly] [--raw|--json] [--timeout <seconds>]
    behavior:
      - fetches better_forecast once
      - renders daily and/or hourly sections
```

### Global flags
- `--raw`: suppresses leading sentence and prints only core lines
- `--json`: prints API response JSON and exits
- `--timeout`: HTTP timeout in seconds; defaults to `TEMPEST_TIMEOUT_S` or `8`

### Argument normalization requirement
Global flags must be accepted **before or after** subcommands (e.g., `tempest-cli --raw current` and `tempest-cli current --raw` both valid).

## 3) Data Fetch Contract

### Request
- Method: `GET`
- URL: `better_forecast` endpoint with station ID, token, and fixed unit query params
- Timeout: user-selected/global default

### Response expectation
```yaml
response_contract:
  top_level_type: object
  expected_sections:
    - current_conditions (object)
    - forecast.daily (array)
    - forecast.hourly (array)
```

If response is not a JSON object, the command must terminate with an error.

## 4) Output Contracts

## 4.1 Current (`current`)
When `current_conditions` is unavailable or empty, return:
- `No current conditions available.`

Otherwise render available lines in this order (omit any missing field lines):
1. `Cond <conditions>` from `conditions` or `condition`
2. `Temp <air_temperature>°` (1 decimal)
3. `FeelsLike <feels_like>°` (1 decimal)
4. Wind line from `wind_avg`, optional `wind_gust`, optional direction (`wind_direction_cardinal` or `wind_direction`):
   - `Wind <dir> <avg> G <gust> mph`
   - `Wind <dir> <avg> mph`
   - `Wind <avg> G <gust> mph`
   - `Wind <avg> mph`
5. `Humidity <relative_humidity>%` (0 decimals)
6. `Pressure <sea_level_pressure> inHg` (2 decimals)
7. `Precip <precip_accum_local_day> in` (2 decimals)
8. `UV (index) <uv>` (trim trailing `.0`)
9. `SolarRad <solar_radiation> W/m^2` (0 decimals)
10. `Brightness <brightness> lux` (0 decimals)
11. `Sunrise <local time>` / `Sunset <local time>` if epoch appears valid
12. `Updated <local timestamp>` (**always last**)

## 4.2 Forecast (`forecast`)
- `--daily`: daily section + `Updated` line
- `--hourly`: hourly section + `Updated` line
- no section flag: daily + blank line + hourly + `Updated`

## 4.3 Daily format
Header line:
- `Daily:`

Entry format target (for each day, up to 10 days):
- `Mon 4  Hi 63° - Lo 44°, Partly Cloudy, Rain 40%, Sunrise 7:02 AM, Sunset 6:21 PM`

Daily mapping rules:
- label date currently based on local `today + (index + 1)`
- condition from `conditions` or `condition` (fallback `—`)
- highs/lows from `air_temp_high`, `air_temp_low`
- optional precip phrase from `precip_type` + `precip_probability`
- optional sunrise/sunset from daily epoch values

## 4.4 Hourly format
Header line:
- `Hourly:`

Entry format target (for each hour, up to 12 hours):
- `Mon 5 PM 62° FeelsLike 61° Precip 0.02" Wind SW 10 G15 mph, Cloudy, Rain 35%`

Hourly mapping rules:
- timestamp from `time` epoch; fallback `now + index hours`
- include temp, optional feels-like, optional precip amount, wind summary, condition, optional precip descriptor

## 5) Time and Localization Rules

```yaml
time_rules:
  timezone: local system timezone
  sunrise_sunset_epoch_guard: "> 10000"
  updated_format: "h:mm:ss AM/PM  m/d/YYYY"
  hourly_time_label: "h AM/PM"
```

Sunrise/sunset fallback search order:
1. `current_conditions` keys: `sunrise|sunrise_ts|sunrise_epoch`, `sunset|sunset_ts|sunset_epoch`
2. `forecast.daily[0]` same key set
3. `station` or `location` block same key set

## 6) Error Handling Requirements

- Missing required env vars must exit with:
  - `error: missing required env var <NAME>`
- Timeout must exit with:
  - `error: Tempest request timed out after <N>s`
- HTTP status failures must exit with:
  - `error: Tempest HTTP error: <details>`
- Other fetch/parse exceptions must exit with:
  - `error: Tempest fetch failed: <Type>: <details>`

If stderr is a TTY, errors should be ANSI red.

## 7) Non-Functional Requirements
- Single API call per invocation
- No persistent cache
- Portable CLI behavior on macOS/Linux with Python 3
- Output must be stable and line-oriented for downstream parsing

## 8) Implementation Structure

```yaml
functions:
  - _load_env_fallback
  - _get_required_env
  - _better_forecast_url
  - fetch_better_forecast
  - _parse_current
  - _parse_daily
  - _parse_hourly
  - build_parser
  - main
```

### Main flow
1. Normalize argv for global flag placement
2. Parse args
3. Fetch data once
4. If `--json`, dump JSON and exit
5. Render command-specific text output
6. Exit `0`

## 9) Acceptance Tests (Behavioral)

```yaml
test_matrix:
  - case: no_args
    expect: help_text
  - case: current_raw
    cmd: tempest-cli current --raw
    expect:
      - contains: "Updated "
  - case: forecast_daily_raw
    cmd: tempest-cli forecast --daily --raw
    expect:
      - starts_with: "Daily:"
      - contains: "Updated: "
  - case: forecast_hourly_raw
    cmd: tempest-cli forecast --hourly --raw
    expect:
      - starts_with: "Hourly:"
      - contains: "Updated: "
  - case: json_mode
    cmd: tempest-cli current --json
    expect: valid_json_object
  - case: timeout_error
    setup: TEMPEST_TIMEOUT_S=0.001
    expect: graceful_timeout_error
```

## 10) Known Design Notes
- Forecast output appends `Updated: ...` (with colon), while current line uses `Updated ...` (without colon).
- Daily and hourly currently have similar precip labeling logic and may be consolidated in future refactors.
- `time` module import exists but is not functionally required in current implementation.
