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
# Sunrise / sunset fallback
# ----------------------------

def _coerce_epoch(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _pick_epoch(d: Any, keys: List[str]) -> Optional[float]:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d:
            ts = _coerce_epoch(d.get(k))
            if ts is not None:
                return ts
    return None


def _find_sun_times_epoch(data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Return (sunrise_epoch, sunset_epoch) seconds if found in common locations."""
    # 1) current_conditions (older API)
    cc = data.get("current_conditions")
    sunrise = _pick_epoch(cc, ["sunrise", "sunrise_ts", "sunrise_epoch"])
    sunset = _pick_epoch(cc, ["sunset", "sunset_ts", "sunset_epoch"])
    if sunrise is not None or sunset is not None:
        return sunrise, sunset

    # 2) forecast.daily[0] (common in forecast payloads)
    fc = data.get("forecast")
    if isinstance(fc, dict):
        daily = fc.get("daily")
        if isinstance(daily, list) and daily:
            d0 = daily[0] if isinstance(daily[0], dict) else {}
            sunrise = _pick_epoch(d0, ["sunrise", "sunrise_ts", "sunrise_epoch"])
            sunset = _pick_epoch(d0, ["sunset", "sunset_ts", "sunset_epoch"])
            if sunrise is not None or sunset is not None:
                return sunrise, sunset

    # 3) station/location blocks (varies)
    station = data.get("station") or data.get("location")
    if isinstance(station, list) and station:
        station = station[0]
    sunrise = _pick_epoch(station, ["sunrise", "sunrise_ts", "sunrise_epoch"])
    sunset = _pick_epoch(station, ["sunset", "sunset_ts", "sunset_epoch"])
    if sunrise is not None or sunset is not None:
        return sunrise, sunset

    return None, None

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

    conditions = get_str("conditions") or get_str("condition")
    if conditions:
        lines.append(f"Cond {conditions}")

    temp = get_num("air_temperature")
    if temp is not None:
        lines.append(f"Temp {temp:.1f}°")

    chill = get_num("feels_like")
    if chill is not None:
        lines.append(f"FeelsLike {chill:.1f}°")

    wind = get_num("wind_avg")
    gust = get_num("wind_gust")
    wdir = get_str("wind_direction_cardinal") or get_str("wind_direction")
    if wind is not None:
        dir_s = ""
        if wdir:
            if wdir.replace(".", "", 1).isdigit():
                dir_s = f"{wdir}°"
            else:
                dir_s = wdir

        if dir_s and gust is not None:
            lines.append(f"Wind {dir_s} {wind:.0f} G {gust:.0f} mph")
        elif dir_s:
            lines.append(f"Wind {dir_s} {wind:.0f} mph")
        elif gust is not None:
            lines.append(f"Wind {wind:.0f} G {gust:.0f} mph")
        else:
            lines.append(f"Wind {wind:.0f} mph")

    rh = get_num("relative_humidity")
    if rh is not None:
        lines.append(f"Humidity {rh:.0f}%")

    pres = get_num("sea_level_pressure")
    if pres is not None:
        lines.append(f"Pressure {pres:.2f} inHg")

    precip = get_num("precip_accum_local_day")
    if precip is not None:
        lines.append(f"Precip {precip:.2f} in")

    uv = get_num("uv")
    if uv is not None:
        # uv is often 0.0–something; keep one decimal max like your examples
        lines.append(f"UV (index) {uv:.1f}".rstrip("0").rstrip("."))

    solar_rad = get_num("solar_radiation")
    if solar_rad is not None:
        lines.append(f"SolarRad {solar_rad:.0f} W/m^2")

    brightness = get_num("brightness")
    if brightness is not None:
        lines.append(f"Brightness {brightness:.0f} lux")

    # Sunrise/Sunset (local times)
    sunrise = get_num("sunrise")
    sunset = get_num("sunset")

    # Fallback if API no longer includes sunrise/sunset in current_conditions
    if sunrise is None and sunset is None:
        sunrise, sunset = _find_sun_times_epoch(data)

    # The API commonly returns unix epoch seconds for sunrise/sunset.
    # Convert to local time if plausible.
    def fmt_epoch_local(ts: float) -> str:
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%I:%M %p").lstrip("0")

    if sunrise is not None and sunrise > 10_000:  # crude guard
        lines.append(f"Sunrise {fmt_epoch_local(sunrise)}")
    if sunset is not None and sunset > 10_000:
        lines.append(f"Sunset {fmt_epoch_local(sunset)}")

    # Updated goes LAST (per your requirement)
    lines.append(f"Updated {_local_updated_stamp()}")

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

    def fmt_epoch_local(ts: float) -> str:
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%I:%M %p").lstrip("0")

    for i in range(take):
        d = daily[i]
        if not isinstance(d, dict):
            continue

        label_date = base_date + timedelta(days=i + 1)
        label = f"{label_date.strftime('%a')} {label_date.day}"

        hi = d.get("air_temp_high")
        lo = d.get("air_temp_low")
        cond = d.get("conditions") or d.get("condition") or "—"
        precip_type_raw = str(d.get("precip_type") or "").strip().lower()
        precip_probability = d.get("precip_probability")
        precip_probability_v: Optional[float] = None
        precip_probability_s: Optional[str] = None
        try:
            if precip_probability is not None:
                precip_probability_v = float(precip_probability)
                precip_probability_s = f"{precip_probability_v:.0f}"
        except Exception:
            precip_probability_v = None
            precip_probability_s = None

        precip_desc: Optional[str] = None
        if precip_probability_v is not None and precip_probability_v <= 0:
            precip_desc = "Precip"
        elif precip_type_raw and precip_type_raw != "none":
            precip_type = precip_type_raw.replace("_", " ").title()
            precip_desc = f"{precip_type} {precip_probability_s}%" if precip_probability_s is not None else precip_type

        cond_with_precip = f"{cond}, {precip_desc}" if precip_desc else cond

        # temps already °F because units_temp=f
        try:
            hi_s = f"{float(hi):.0f}°" if hi is not None else ""
        except Exception:
            hi_s = ""
        try:
            lo_s = f"{float(lo):.0f}°" if lo is not None else ""
        except Exception:
            lo_s = ""

        sunrise_s = ""
        sunset_s = ""
        sunrise = _coerce_epoch(d.get("sunrise"))
        sunset = _coerce_epoch(d.get("sunset"))
        if sunrise is not None and sunrise > 10_000:
            sunrise_s = f"Sunrise {fmt_epoch_local(sunrise)}"
        if sunset is not None and sunset > 10_000:
            sunset_s = f"Sunset {fmt_epoch_local(sunset)}"

        sun_parts = ", ".join(part for part in [sunrise_s, sunset_s] if part)
        sun_suffix = f", {sun_parts}" if sun_parts else ""

        if hi_s and lo_s:
            out.append(f"{label}  Hi {hi_s} - Lo {lo_s}, {cond_with_precip}{sun_suffix}")
        elif lo_s:
            out.append(f"{label}  Lo {lo_s}, {cond_with_precip}{sun_suffix}")
        else:
            out.append(f"{label}, {cond_with_precip}{sun_suffix}")

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

        dlabel = dt.strftime("%a")
        tlabel = _hh_ampm(dt)

        temp = h.get("air_temperature")
        wind = h.get("wind_avg")
        gust = h.get("wind_gust")
        wdir = h.get("wind_direction_cardinal") or h.get("wind_direction")
        cond = h.get("conditions") or h.get("condition") or "—"
        precip_type_raw = str(h.get("precip_type") or "").strip().lower()
        precip_probability = h.get("precip_probability")
        precip_probability_v: Optional[float] = None
        precip_probability_s: Optional[str] = None
        try:
            if precip_probability is not None:
                precip_probability_v = float(precip_probability)
                precip_probability_s = f"{precip_probability_v:.0f}"
        except Exception:
            precip_probability_v = None
            precip_probability_s = None

        precip_desc: Optional[str] = None
        if precip_probability_v is not None and precip_probability_v <= 0:
            precip_desc = "Precip"
        elif precip_type_raw and precip_type_raw != "none":
            precip_type = precip_type_raw.replace("_", " ").title()
            precip_desc = f"{precip_type} {precip_probability_s}%" if precip_probability_s is not None else precip_type

        cond_with_precip = f"{cond}, {precip_desc}" if precip_desc else cond

        # temps already °F, wind already mph
        try:
            temp_s = f"{float(temp):.0f}°" if temp is not None else "—"
        except Exception:
            temp_s = "—"
        try:
            wind_v = float(wind) if wind is not None else None
        except Exception:
            wind_v = None
        try:
            gust_v = float(gust) if gust is not None else None
        except Exception:
            gust_v = None
        try:
            feels_like_s = f"FeelsLike {float(h.get('feels_like')):.0f}°" if h.get("feels_like") is not None else ""
        except Exception:
            feels_like_s = ""
        try:
            precip_amt_s = f"Precip {float(h.get('precip')):.2f}\"" if h.get("precip") is not None else ""
        except Exception:
            precip_amt_s = ""
        wdir_s = ""
        if wdir is not None:
            wdir_s = str(wdir)

        wind_s = ""
        if wind_v is not None:
            if wdir_s and gust_v is not None:
                wind_s = f"Wind {wdir_s} {wind_v:.0f} G{gust_v:.0f} mph"
            elif wdir_s:
                wind_s = f"Wind {wdir_s} {wind_v:.0f} mph"
            elif gust_v is not None:
                wind_s = f"Wind {wind_v:.0f} G{gust_v:.0f} mph"
            else:
                wind_s = f"Wind {wind_v:.0f} mph"

        if wind_s:
            extras = " ".join(part for part in [feels_like_s, precip_amt_s] if part)
            extra_prefix = f" {extras}" if extras else ""
            out.append(f"{dlabel} {tlabel} {temp_s}{extra_prefix} {wind_s}, {cond_with_precip}".rstrip())
        else:
            extras = " ".join(part for part in [feels_like_s, precip_amt_s] if part)
            extra_prefix = f" {extras}" if extras else ""
            out.append(f"{dlabel} {tlabel} {temp_s}{extra_prefix}, {cond_with_precip}".rstrip())

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

        # Allow global flags (--raw/--json/--timeout) anywhere (before or after subcommand).
    # argparse only guarantees global options work before the subcommand, so we normalize argv.
    def _normalize_argv(a: List[str]) -> List[str]:
        globals_: List[str] = []
        rest: List[str] = []
        i = 0
        while i < len(a):
            tok = a[i]
            if tok in ("--raw", "--json"):
                globals_.append(tok)
                i += 1
                continue
            if tok == "--timeout":
                if i + 1 >= len(a):
                    rest.append(tok)
                    i += 1
                    continue
                globals_.extend([tok, a[i + 1]])
                i += 2
                continue
            if tok.startswith("--timeout="):
                globals_.append(tok)
                i += 1
                continue
            rest.append(tok)
            i += 1
        return globals_ + rest

    argv = _normalize_argv(argv)

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