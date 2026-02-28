#!/usr/bin/env python3
"""
tempest-cli.py — Tempest (WeatherFlow) home weather tool

Commands:
  tempest-cli current [--raw|--json]
  tempest-cli forecast [--raw|--json] [--days N] [--hours N]

Notes:
- The Tempest REST API returns metric SI units; we convert for display.  (C→F, m/s→mph, mb→inHg, mm→in)
- API key is read from environment: TEMPEST_API_KEY
- Station ID defaults to env TEMPEST_STATION_ID, else hardcoded fallback.

Exit codes:
  0 ok
  2 usage / unknown command
  3 missing config
  4 network/api error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import requests

# -----------------------------
# Config (NO hard-coded paths)
# -----------------------------

DEFAULT_STATION_ID = "161526"

API_KEY_ENV = "TEMPEST_API_KEY"
STATION_ID_ENV = "TEMPEST_STATION_ID"

# Optional: if you want the tool itself to load dotenv in dev, set TEMPEST_DOTENV=/path/to/.env
DOTENV_PATH_ENV = "TEMPEST_DOTENV"


# -----------------------------
# Small helpers
# -----------------------------

ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def local_stamp() -> str:
    # Example: 3:00:29 PM  2/28/2026 (macOS supports %-m etc; keep portable)
    now = datetime.now().astimezone()
    # Portable “no leading zero” formatting:
    t = now.strftime("%I:%M:%S %p").lstrip("0")
    m = now.strftime("%m").lstrip("0")
    d = now.strftime("%d").lstrip("0")
    y = now.strftime("%Y")
    return f"{t}  {m}/{d}/{y}"


def c_to_f(c: float) -> float:
    return (c * 9.0 / 5.0) + 32.0


def ms_to_mph(ms: float) -> float:
    return ms * 2.2369362920544


def mb_to_inhg(mb: float) -> float:
    return mb * 0.029529983071445


def mm_to_in(mm: float) -> float:
    return mm * 0.039370078740157


def degrees_to_compass(deg: float) -> str:
    # 16-wind compass
    idx = int((deg / 22.5) + 0.5)
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[idx % 16]


def load_dotenv_if_configured() -> None:
    path = os.getenv(DOTENV_PATH_ENV)
    if not path:
        return
    try:
        # Optional dependency
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    try:
        if os.path.exists(path):
            load_dotenv(path, override=False)
    except Exception:
        pass


def get_api_key() -> Optional[str]:
    load_dotenv_if_configured()
    return os.getenv(API_KEY_ENV)


def get_station_id() -> str:
    load_dotenv_if_configured()
    return os.getenv(STATION_ID_ENV, DEFAULT_STATION_ID)


# -----------------------------
# HTTP
# -----------------------------

@dataclass
class FetchResult:
    json_data: Dict[str, Any]
    elapsed_ms: int


def http_get_json(url: str, timeout_s: float = 5.0) -> FetchResult:
    started = time.time()
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    elapsed_ms = int((time.time() - started) * 1000)
    if not isinstance(data, dict):
        raise ValueError("API returned non-object JSON")
    return FetchResult(json_data=data, elapsed_ms=elapsed_ms)


def tempest_station_observations_url(station_id: str, api_key: str) -> str:
    return f"https://swd.weatherflow.com/swd/rest/observations/station/{station_id}?api_key={api_key}"


def tempest_better_forecast_url(station_id: str, api_key: str) -> str:
    # The “better_forecast” endpoint returns current + hourly + daily in one response.
    return f"https://swd.weatherflow.com/swd/rest/better_forecast?station_id={station_id}&api_key={api_key}"


# -----------------------------
# Formatting: CURRENT
# -----------------------------

def format_current_from_observations(data: Dict[str, Any]) -> list[str]:
    obs = data.get("obs") or []
    if not obs or not isinstance(obs, list):
        raise ValueError("No observation data available.")

    latest = obs[-1]
    if not isinstance(latest, dict):
        raise ValueError("Invalid observation format.")

    lines: list[str] = []

    # The REST API uses metric SI; convert for display.  [oai_citation:1‡The Tempest Weather Community](https://community.tempest.earth/t/converting-units-of-measure/16760?utm_source=chatgpt.com)
    if "air_temperature" in latest:
        lines.append(f"Temperature: {c_to_f(float(latest['air_temperature'])):.1f} °F")

    if "wind_chill" in latest:
        lines.append(f"Wind Chill: {c_to_f(float(latest['wind_chill'])):.1f} °F")

    if "wind_avg" in latest:
        mph = ms_to_mph(float(latest["wind_avg"]))
        wind_dir = degrees_to_compass(float(latest.get("wind_direction", 0.0)))
        lines.append(f"Wind: {mph:.1f} mph {wind_dir}")

    if "relative_humidity" in latest:
        lines.append(f"Humidity: {float(latest['relative_humidity']):.0f} %")

    if "barometric_pressure" in latest:
        lines.append(f"Pressure: {mb_to_inhg(float(latest['barometric_pressure'])):.2f} inHg")

    if "precip" in latest:
        lines.append(f"Precipitation: {mm_to_in(float(latest['precip'])):.2f} in")

    if "uv" in latest:
        lines.append(f"UV Index: {float(latest['uv']):.1f}")

    return lines


# -----------------------------
# Formatting: FORECAST
# -----------------------------

def _safe_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    v = d.get(key, default)
    return v


def format_forecast_from_better_forecast(
    data: Dict[str, Any],
    days: int = 10,
    hours: int = 12,
) -> list[str]:
    """
    We produce:
      - Daily forecast: next N days
      - Hourly forecast: next N hours
    Then add Updated: ... as last line.
    """
    lines: list[str] = []

    # Structures vary slightly; keep it defensive.
    forecast = data.get("forecast") or data

    daily = None
    hourly = None

    if isinstance(forecast, dict):
        daily = forecast.get("daily")
        hourly = forecast.get("hourly")

    if not isinstance(daily, list) and isinstance(forecast, dict):
        # Some shapes use "days"/"hours" keys, keep fallback
        daily = forecast.get("days")
        hourly = forecast.get("hours")

    if not isinstance(daily, list):
        daily = []
    if not isinstance(hourly, list):
        hourly = []

    # Daily
    lines.append("Daily:")
    for i, day in enumerate(daily[: max(0, days)]):
        if not isinstance(day, dict):
            continue
        # try to find a label/date
        day_name = _safe_get(day, "day_name") or _safe_get(day, "dow") or f"Day {i+1}"
        cond = _safe_get(day, "conditions") or _safe_get(day, "icon") or "—"
        # temps commonly in C
        t_hi_c = _safe_get(day, "air_temp_high")
        t_lo_c = _safe_get(day, "air_temp_low")

        parts = [f"{day_name}:"]
        if t_hi_c is not None and t_lo_c is not None:
            parts.append(f"High {c_to_f(float(t_hi_c)):.0f}° / Low {c_to_f(float(t_lo_c)):.0f}°")
        elif t_lo_c is not None:
            parts.append(f"Low {c_to_f(float(t_lo_c)):.0f}°")
        parts.append(f"— {cond}")
        lines.append(" ".join(parts))

    # Hourly
    lines.append("")
    lines.append("Hourly:")
    for hr in hourly[: max(0, hours)]:
        if not isinstance(hr, dict):
            continue
        # time
        # Many payloads provide "time" as unix seconds.
        ts = _safe_get(hr, "time")
        label = None
        if isinstance(ts, (int, float)):
            label = datetime.fromtimestamp(float(ts)).astimezone().strftime("%-I %p") if sys.platform != "win32" else datetime.fromtimestamp(float(ts)).astimezone().strftime("%I %p").lstrip("0")
        else:
            label = _safe_get(hr, "hour") or "Hour"

        cond = _safe_get(hr, "conditions") or _safe_get(hr, "icon") or "—"
        t_c = _safe_get(hr, "air_temperature")
        wind_ms = _safe_get(hr, "wind_avg") or _safe_get(hr, "wind_speed")
        wind_dir_deg = _safe_get(hr, "wind_direction", 0.0)

        bits = [f"{label}:"]
        if t_c is not None:
            bits.append(f"{c_to_f(float(t_c)):.0f}°")
        if wind_ms is not None:
            bits.append(f"{ms_to_mph(float(wind_ms)):.0f} mph {degrees_to_compass(float(wind_dir_deg))}")
        bits.append(f"— {cond}")
        lines.append(" ".join(bits))

    return lines


# -----------------------------
# CLI
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tempest-cli",
        add_help=True,
        description="Tempest home weather tool (current conditions and forecast).",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command")

    def add_common_flags(p: argparse.ArgumentParser) -> None:
        g = p.add_mutually_exclusive_group()
        g.add_argument("--raw", action="store_true", help="Raw text only (no leading sentence).")
        g.add_argument("--json", action="store_true", help="Dump raw API JSON.")
        p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds (default: 5.0)")

    p_current = sub.add_parser("current", help="Current conditions at home")
    add_common_flags(p_current)

    p_forecast = sub.add_parser("forecast", help="Forecast at home (daily + hourly)")
    add_common_flags(p_forecast)
    p_forecast.add_argument("--days", type=int, default=10, help="Daily days to show (default: 10)")
    p_forecast.add_argument("--hours", type=int, default=12, help="Hourly hours to show (default: 12)")

    return parser


def print_help_and_exit(parser: argparse.ArgumentParser, code: int = 0) -> int:
    parser.print_help(sys.stdout)
    return code


def main(argv: list[str]) -> int:
    parser = build_parser()

    if len(argv) == 0:
        return print_help_and_exit(parser, 0)

    # Custom “unknown command” in red
    if argv and not argv[0].startswith("-") and argv[0] not in {"current", "forecast"}:
        eprint(f"{ANSI_RED}error:{ANSI_RESET} unknown command {argv[0]!r}")
        eprint("")
        return print_help_and_exit(parser, 2)

    args = parser.parse_args(argv)

    api_key = get_api_key()
    if not api_key:
        eprint(f"{ANSI_RED}error:{ANSI_RESET} {API_KEY_ENV} is not set")
        return 3

    station_id = get_station_id()

    try:
        if args.command == "current":
            url = tempest_station_observations_url(station_id, api_key)
            res = http_get_json(url, timeout_s=args.timeout)

            if args.json:
                print(json.dumps(res.json_data, indent=2, sort_keys=True))
                return 0

            lines = format_current_from_observations(res.json_data)

            # Output rules:
            # - no modifier => include leading sentence
            # - --raw => no sentence
            if not args.raw:
                print("The current conditions at your house are:")
            for ln in lines:
                print(ln)
            print(f"Updated: {local_stamp()}")
            return 0

        if args.command == "forecast":
            url = tempest_better_forecast_url(station_id, api_key)
            res = http_get_json(url, timeout_s=args.timeout)

            if args.json:
                print(json.dumps(res.json_data, indent=2, sort_keys=True))
                return 0

            lines = format_forecast_from_better_forecast(res.json_data, days=args.days, hours=args.hours)

            if not args.raw:
                print("The forecast at your house is:")
            for ln in lines:
                print(ln)
            print(f"Updated: {local_stamp()}")
            return 0

        # Should not happen due to earlier checks
        return print_help_and_exit(parser, 2)

    except requests.HTTPError as e:
        eprint(f"{ANSI_RED}error:{ANSI_RESET} API request failed: {e}")
        return 4
    except requests.Timeout:
        eprint(f"{ANSI_RED}error:{ANSI_RESET} API request timed out")
        return 4
    except Exception as e:
        eprint(f"{ANSI_RED}error:{ANSI_RESET} {type(e).__name__}: {e}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))