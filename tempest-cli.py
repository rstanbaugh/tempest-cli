#!/usr/bin/env python3
"""
tempest-cli.py — Tempest (WeatherFlow) station CLI

Commands:
  tempest-cli current  [--raw|--json]
  tempest-cli forecast [--raw|--json] [--daily|--hourly]

Environment (required):
  TEMPEST_API_KEY       # personal access token (Tempest / WeatherFlow)
  TEMPEST_STATION_ID    # e.g. 161526

Optional:
  TEMPEST_TIMEOUT_S     # default 8
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


DOTENV_PATH = os.path.expanduser("~/.openclaw/.env")


# ----------------------------
# Formatting helpers
# ----------------------------

def _local_updated_stamp(now: Optional[datetime] = None) -> str:
    # "4:20:25 PM  2/28/2026"
    dt = now or datetime.now().astimezone()
    time_part = dt.strftime("%I:%M:%S %p").lstrip("0")
    date_part = dt.strftime("%m/%d/%Y")
    # remove leading zeros in m/d (portable-ish)
    date_part = date_part.replace("/0", "/").lstrip("0")
    return f"{time_part}  {date_part}"


def _hh_ampm(dt: datetime) -> str:
    # "5 PM" / "12 AM"
    s = dt.strftime("%I %p").lstrip("0")
    return s


def _red(s: str) -> str:
    if sys.stderr.isatty():
        return f"\033[31m{s}\033[0m"
    return s


# ----------------------------
# Tempest API
# ----------------------------

def _load_env_fallback() -> None:
    # Prefer process env (launchd), but allow ~/.openclaw/.env for CLI usage.
    if load_dotenv and os.path.exists(DOTENV_PATH):
        load_dotenv(DOTENV_PATH, override=False)


def _get_required_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise SystemExit(_red(f"error: missing required env var {name}"))
    return val


def _better_forecast_url(station_id: str, token: str) -> str:
    # Force units to what you want:
    # temp=f, wind=mph, pressure=inhg, precip=in, distance=mi
    # (Tempest supports these on better_forecast)
    return (
        "https://swd.weatherflow.com/swd/rest/better_forecast"
        f"?station_id={station_id}"
        f"&token={token}"
        "&units_temp=f"
        "&units_wind=mph"
        "&units_pressure=inhg"
        "&units_precip=in"
        "&units_distance=mi"
    )


def fetch_better_forecast(timeout_s: float) -> Dict[str, Any]:
    _load_env_fallback()

    token = _get_required_env("TEMPEST_API_KEY")
    station_id = _get_required_env("TEMPEST_STATION_ID")

    url = _better_forecast_url(station_id=station_id, token=token)
    try:
        r = requests.get(url, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("unexpected JSON shape")
        return data
    except requests.Timeout:
        raise SystemExit(_red(f"error: Tempest request timed out after {timeout_s:.1f}s"))
    except requests.HTTPError as e:
        raise SystemExit(_red(f"error: Tempest HTTP error: {e}"))
    except Exception as e:
        raise SystemExit(_red(f"error: Tempest fetch failed: {type(e).__name__}: {e}"))


# ----------------------------
# Parsers (better_forecast)
# ----------------------------

def _parse_current(data: Dict[str, Any]) -> List[str]:
    cc = data.get("current_conditions") or {}
    if not isinstance(cc, dict) or not cc:
        return ["No current conditions available."]

    lines: List[str] = []

    # These values should already be in requested units because we set units_* query params.
    # But we still guard for missing keys.
    def get_num(k: str) -> Optional[float]:
        v = cc.get(k)
        try:
            return float(v)
        except Exception:
            return None

    def get_str(k: str) -> Optional[str]:
        v = cc.get(k)
        return str(v) if v is not None else None

    temp = get_num("air_temperature")
    if temp is not None:
        lines.append(f"Temperature: {temp:.1f} °F")

    chill = get_num("feels_like")
    if chill is not None:
        lines.append(f"Wind Chill: {chill:.1f} °F")

    wind = get_num("wind_avg")
    wdir = get_str("wind_direction_cardinal") or get_str("wind_direction")
    if wind is not None:
        # If wdir is numeric degrees, we just show it; if cardinal, show that.
        if wdir and wdir.replace(".", "", 1).isdigit():
            lines.append(f"Wind: {wind:.0f} mph {wdir}°")
        elif wdir:
            lines.append(f"Wind: {wind:.0f} mph {wdir}")
        else:
            lines.append(f"Wind: {wind:.0f} mph")

    rh = get_num("relative_humidity")
    if rh is not None:
        lines.append(f"Humidity: {rh:.0f} %")

    pres = get_num("sea_level_pressure")
    if pres is not None:
        lines.append(f"Pressure: {pres:.2f} inHg")

    precip = get_num("precip_accum_local_day")
    if precip is not None:
        lines.append(f"Precipitation: {precip:.2f} in")

    uv = get_num("uv")
    if uv is not None:
        # uv is often 0.0–something; keep one decimal max like your examples
        lines.append(f"UV Index: {uv:.1f}".rstrip("0").rstrip("."))

    # Sunrise/Sunset (local times)
    sunrise = get_num("sunrise")
    sunset = get_num("sunset")

    # The API commonly returns unix epoch seconds for sunrise/sunset.
    # Convert to local time if plausible.
    def fmt_epoch_local(ts: float) -> str:
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%I:%M %p").lstrip("0")

    if sunrise is not None and sunrise > 10_000:  # crude guard
        lines.append(f"Sunrise: {fmt_epoch_local(sunrise)}")
    if sunset is not None and sunset > 10_000:
        lines.append(f"Sunset: {fmt_epoch_local(sunset)}")

    # Updated goes LAST (per your requirement)
    lines.append(f"Updated: {_local_updated_stamp()}")

    return lines


def _parse_daily(data: Dict[str, Any], days: int = 10) -> List[str]:
    fc = data.get("forecast") or {}
    daily = fc.get("daily") if isinstance(fc, dict) else None
    if not isinstance(daily, list) or not daily:
        return ["Daily:", "No daily forecast available."]

    out: List[str] = ["Daily:"]

    # API daily[0] is typically tomorrow (today+1). You wanted labels based on today+N.
    base_date = datetime.now().astimezone().date()
    take = min(days, len(daily))

    for i in range(take):
        d = daily[i]
        if not isinstance(d, dict):
            continue

        label_date = base_date + timedelta(days=i + 1)
        label = f"{label_date.strftime('%a')} {label_date.day}"

        hi = d.get("air_temp_high")
        lo = d.get("air_temp_low")
        cond = d.get("conditions") or d.get("condition") or "—"

        # temps already °F because units_temp=f
        try:
            hi_s = f"{float(hi):.0f}°" if hi is not None else ""
        except Exception:
            hi_s = ""
        try:
            lo_s = f"{float(lo):.0f}°" if lo is not None else ""
        except Exception:
            lo_s = ""

        if hi_s and lo_s:
            out.append(f"{label}: High {hi_s} / Low {lo_s} — {cond}")
        elif lo_s:
            out.append(f"{label}: Low {lo_s} — {cond}")
        else:
            out.append(f"{label}: — {cond}")

    return out


def _parse_hourly(data: Dict[str, Any], hours: int = 12) -> List[str]:
    fc = data.get("forecast") or {}
    hourly = fc.get("hourly") if isinstance(fc, dict) else None
    if not isinstance(hourly, list) or not hourly:
        return ["Hourly:", "No hourly forecast available."]

    out: List[str] = ["Hourly:"]

    take = min(hours, len(hourly))
    for i in range(take):
        h = hourly[i]
        if not isinstance(h, dict):
            continue

        # Prefer API-provided timestamp if present; else label as +i hours
        ts = h.get("time")
        dt: Optional[datetime] = None
        try:
            if ts is not None:
                dt = datetime.fromtimestamp(float(ts)).astimezone()
        except Exception:
            dt = None
        if dt is None:
            dt = datetime.now().astimezone() + timedelta(hours=i)

        tlabel = _hh_ampm(dt)

        temp = h.get("air_temperature")
        wind = h.get("wind_avg")
        wdir = h.get("wind_direction_cardinal") or h.get("wind_direction")
        cond = h.get("conditions") or h.get("condition") or ""

        # temps already °F, wind already mph
        try:
            temp_s = f"{float(temp):.0f}°" if temp is not None else "—"
        except Exception:
            temp_s = "—"
        try:
            wind_s = f"{float(wind):.0f} mph" if wind is not None else ""
        except Exception:
            wind_s = ""
        wdir_s = ""
        if wdir is not None:
            wdir_s = str(wdir)

        if wind_s and wdir_s:
            out.append(f"{tlabel}: {temp_s} {wind_s} {wdir_s} — {cond}".rstrip())
        elif wind_s:
            out.append(f"{tlabel}: {temp_s} {wind_s} — {cond}".rstrip())
        else:
            out.append(f"{tlabel}: {temp_s} — {cond}".rstrip())

    return out


# ----------------------------
# CLI
# ----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tempest-cli",
        description="Tempest (WeatherFlow) CLI for current conditions and forecast.",
        add_help=True,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    p.add_argument(
        "--raw",
        action="store_true",
        help="Print only the core output (no leading sentence).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Dump raw JSON from the API call.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TEMPEST_TIMEOUT_S", "8")),
        help="HTTP timeout seconds (default: env TEMPEST_TIMEOUT_S or 8).",
    )

    sub = p.add_subparsers(dest="command")

    sub.add_parser("current", help="Show current conditions (includes sunrise/sunset).")

    f = sub.add_parser("forecast", help="Show forecast (daily + hourly by default).")
    f.add_argument("--daily", action="store_true", help="Show only the daily forecast section.")
    f.add_argument("--hourly", action="store_true", help="Show only the hourly forecast section.")

    return p


def _print_lines(lines: List[str]) -> None:
    sys.stdout.write("\n".join(lines).rstrip() + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Default behavior: no args => help
    if not argv:
        build_parser().print_help(sys.stdout)
        return 0

    # Catch unknown "command" early to give a clean error
    # (argparse does this too, but you asked for `error: unknown command 'xxx'`)
    known_cmds = {"current", "forecast", "-h", "--help"}
    first = argv[0]
    if first.startswith("-") is False and first not in known_cmds:
        sys.stderr.write(_red(f"error: unknown command '{first}'") + "\n")
        return 2

    args = build_parser().parse_args(argv)

    # Pull data once (forecast endpoint includes current + forecast)
    data = fetch_better_forecast(timeout_s=args.timeout)

    if args.json:
        sys.stdout.write(json.dumps(data, indent=2, sort_keys=False) + "\n")
        return 0

    if args.command == "current":
        core = _parse_current(data)
        if args.raw:
            _print_lines(core)
        else:
            _print_lines(["The current conditions at your house are:", *core])
        return 0

    if args.command == "forecast":
        only_daily = bool(getattr(args, "daily", False))
        only_hourly = bool(getattr(args, "hourly", False))

        daily_lines = _parse_daily(data, days=10)
        hourly_lines = _parse_hourly(data, hours=12)

        # Updated should be last line overall. It's already last in _parse_current,
        # but forecast needs its own final Updated stamp.
        updated_line = f"Updated: {_local_updated_stamp()}"

        sections: List[str] = []
        if only_daily and not only_hourly:
            sections = [*daily_lines, updated_line]
        elif only_hourly and not only_daily:
            sections = [*hourly_lines, updated_line]
        else:
            # default: both
            sections = [*daily_lines, "", *hourly_lines, updated_line]

        if args.raw:
            _print_lines(sections)
        else:
            _print_lines(["The forecast at your house is:", *sections])
        return 0

    # If argparse let something through, show help
    build_parser().print_help(sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())