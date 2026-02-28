#!/usr/bin/env python3
"""
Tempest CLI

Single-file CLI for fetching:
- current conditions (Tempest better_forecast current_conditions)
- forecast (better_forecast daily + hourly)

Design goals:
- deterministic stdout for skill consumption
- no hard-coded paths (everything via env + wrapper)
- supports: current/forecast + modifiers: --raw, --json, --daily, --hourly, --days N, --hours N
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

# ----------------------------
# Formatting helpers
# ----------------------------

RED = "\033[31m"
RESET = "\033[0m"


def _now_local_stamp() -> str:
    # Example: 4:04:19 PM  2/28/2026
    try:
        return datetime.now().astimezone().strftime("%-I:%M:%S %p  %-m/%-d/%Y")
    except Exception:
        s = datetime.now().astimezone().strftime("%I:%M:%S %p  %m/%d/%Y")
        return s.lstrip("0").replace("/0", "/")


def _fmt_time_hm(epoch_s: Optional[int]) -> Optional[str]:
    if epoch_s is None:
        return None
    try:
        dt = datetime.fromtimestamp(int(epoch_s)).astimezone()
        try:
            return dt.strftime("%-I:%M %p")
        except Exception:
            return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return None


def _day_label_from_epoch(epoch_s: Optional[int]) -> str:
    # "Sun 1"
    if epoch_s is None:
        return "Day"
    dt = datetime.fromtimestamp(int(epoch_s)).astimezone()
    return f"{dt.strftime('%a')} {dt.day}"


def _mph_from_mps(mps: float) -> float:
    return mps * 2.2369362920544


def _inhg_from_mb(mb: float) -> float:
    return mb * 0.0295299830714


def _in_from_mm(mm: float) -> float:
    return mm / 25.4


def _deg_to_cardinal(deg: float) -> str:
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    try:
        val = int((deg / 22.5) + 0.5)
        return directions[val % 16]
    except Exception:
        return "N"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _coerce_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


# ----------------------------
# Env + URL helpers
# ----------------------------

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


def _required_env(name: str) -> str:
    val = _env(name)
    if not val:
        raise RuntimeError(f"{name} is not set.")
    return val


def _station_id() -> int:
    raw = _env("TEMPEST_STATION_ID", "161526")
    try:
        return int(raw)  # type: ignore[arg-type]
    except Exception:
        raise RuntimeError("TEMPEST_STATION_ID must be an integer.")


def _base_url() -> str:
    return (_env("TEMPEST_BASE_URL", "https://swd.weatherflow.com") or "https://swd.weatherflow.com").rstrip("/")


def _better_forecast_url_with_api_key(station_id: int, api_key: str) -> str:
    # Force units so we don't do client-side unit guessing.
    return (
        f"{_base_url()}/swd/rest/better_forecast"
        f"?station_id={station_id}"
        f"&api_key={api_key}"
        f"&units_temp=f"
        f"&units_wind=mph"
        f"&units_pressure=inhg"
        f"&units_precip=in"
        f"&units_distance=mi"
    )


def _better_forecast_url_with_token(station_id: int, device_id: str, token: str) -> str:
    return (
        f"{_base_url()}/swd/rest/better_forecast"
        f"?station_id={station_id}"
        f"&device_id={device_id}"
        f"&token={token}"
        f"&units_temp=f"
        f"&units_wind=mph"
        f"&units_pressure=inhg"
        f"&units_precip=in"
        f"&units_distance=mi"
    )


def _http_get_json(url: str, timeout_s: float = 6.0) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def _fetch_better_forecast(api_key: str, station_id: int) -> Dict[str, Any]:
    url = _better_forecast_url_with_api_key(station_id, api_key)
    try:
        return _http_get_json(url)
    except Exception:
        token = _env("TEMPEST_TOKEN")
        device_id = _env("TEMPEST_DEVICE_ID")
        if token and device_id:
            url2 = _better_forecast_url_with_token(station_id, device_id, token)
            return _http_get_json(url2)
        raise


# ----------------------------
# Renderers
# ----------------------------

def _render_current_from_better_forecast(bf: Dict[str, Any]) -> List[str]:
    cc = bf.get("current_conditions") or {}
    lines: List[str] = []

    temp = _coerce_float(cc.get("air_temperature"))
    chill = _coerce_float(cc.get("feels_like"))
    wind = _coerce_float(cc.get("wind_avg"))
    wind_dir_deg = _coerce_float(cc.get("wind_direction"))
    rh = _coerce_float(cc.get("relative_humidity"))
    pres = _coerce_float(cc.get("sea_level_pressure") or cc.get("barometric_pressure") or cc.get("pressure"))
    precip = _coerce_float(cc.get("precip_accum_local_day") or cc.get("precip_accumulated") or cc.get("precip"))
    uv = _coerce_float(cc.get("uv"))

    # If pressure looks like mb (e.g., 986), convert to inHg.
    pres_inhg: Optional[float] = None
    if pres is not None:
        pres_inhg = pres if pres < 60 else _inhg_from_mb(pres)

    if temp is not None:
        lines.append(f"Temperature: {temp:.1f} °F")
    if chill is not None:
        lines.append(f"Wind Chill: {chill:.1f} °F")
    if wind is not None:
        wd = _deg_to_cardinal(wind_dir_deg or 0.0)
        lines.append(f"Wind: {wind:.0f} mph {wd}")
    if rh is not None:
        lines.append(f"Humidity: {rh:.0f} %")
    if pres_inhg is not None:
        lines.append(f"Pressure: {pres_inhg:.2f} inHg")
    if precip is not None:
        # If inches were requested, this is inches. If it looks like mm, convert.
        precip_in = precip if precip < 10 else _in_from_mm(precip)
        lines.append(f"Precipitation: {precip_in:.2f} in")
    if uv is not None:
        lines.append(f"UV Index: {uv:.1f}")

    # Sunrise/Sunset from daily forecast
    sunrise = None
    sunset = None
    forecast = bf.get("forecast") or {}
    daily = forecast.get("daily") or []
    if isinstance(daily, list) and daily:
        for d in daily[:3]:
            if not isinstance(d, dict):
                continue
            sunrise = sunrise or _coerce_int(d.get("sunrise") or d.get("sunrise_ts") or d.get("sunrise_time"))
            sunset = sunset or _coerce_int(d.get("sunset") or d.get("sunset_ts") or d.get("sunset_time"))
            if sunrise and sunset:
                break

    sr = _fmt_time_hm(sunrise)
    ss = _fmt_time_hm(sunset)
    if sr:
        lines.append(f"Sunrise: {sr}")
    if ss:
        lines.append(f"Sunset: {ss}")

    lines.append(f"Updated: {_now_local_stamp()}")
    return lines


def _render_forecast_text(
    bf: Dict[str, Any],
    show_daily: bool,
    show_hourly: bool,
    days_n: int,
    hours_n: int,
) -> List[str]:
    forecast = bf.get("forecast") or {}
    daily = forecast.get("daily") or []
    hourly = forecast.get("hourly") or []

    lines: List[str] = []

    if show_daily:
        lines.append("Daily:")
        if isinstance(daily, list) and daily:
            for d in daily[: max(0, days_n)]:
                if not isinstance(d, dict):
                    continue
                day_label = _day_label_from_epoch(_coerce_int(d.get("day_start_local") or d.get("day_start") or d.get("time")))
                hi = _coerce_float(d.get("air_temp_high"))
                lo = _coerce_float(d.get("air_temp_low"))
                cond = d.get("conditions") or d.get("condition") or "—"

                # IMPORTANT: do NOT do temp unit guessing here.
                # We force units_temp=f in the request; heuristic conversion caused 50°F -> 122°F bugs.
                if hi is not None and lo is not None:
                    lines.append(f"{day_label}: High {hi:.0f}° / Low {lo:.0f}° — {cond}")
                elif hi is not None:
                    lines.append(f"{day_label}: High {hi:.0f}° — {cond}")
                elif lo is not None:
                    lines.append(f"{day_label}: Low {lo:.0f}° — {cond}")
                else:
                    lines.append(f"{day_label}: {cond}")
        else:
            lines.append("(no daily forecast data)")

    if show_hourly:
        if lines:
            lines.append("")
        lines.append("Hourly:")
        if isinstance(hourly, list) and hourly:
            for h in hourly[: max(0, hours_n)]:
                if not isinstance(h, dict):
                    continue
                ts = _coerce_int(h.get("time") or h.get("time_local") or h.get("ts"))
                dt = datetime.fromtimestamp(ts).astimezone() if ts else None
                if dt:
                    try:
                        label = dt.strftime("%-I %p")
                    except Exception:
                        label = dt.strftime("%I %p").lstrip("0")
                else:
                    label = "(hour)"

                temp = _coerce_float(h.get("air_temperature"))
                wind = _coerce_float(h.get("wind_avg"))
                wind_dir = _coerce_float(h.get("wind_direction"))
                cond = h.get("conditions") or h.get("condition") or ""

                # IMPORTANT: do NOT do temp unit guessing here (prevents double conversion).
                # Wind: request is mph, but if m/s leaks through (small values), convert heuristically.
                if wind is not None and wind < 25 and (h.get("units_wind") in (None, "", "mps")):
                    wind = _mph_from_mps(wind)

                wd = _deg_to_cardinal(wind_dir or 0.0)

                if temp is not None and wind is not None:
                    lines.append(f"{label}: {temp:.0f}° {wind:.0f} mph {wd} — {cond}".rstrip())
                elif temp is not None:
                    lines.append(f"{label}: {temp:.0f}° — {cond}".rstrip())
                else:
                    lines.append(f"{label}: — {cond}".rstrip())
        else:
            lines.append("(no hourly forecast data)")

    lines.append(f"Updated: {_now_local_stamp()}")
    return lines


# ----------------------------
# CLI
# ----------------------------

def _print_error(msg: str) -> int:
    sys.stderr.write(f"{RED}error:{RESET} {msg}\n")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tempest-cli",
        description="Tempest CLI: current conditions and forecast from a Tempest (WeatherFlow) station.",
        add_help=True,
    )
    sub = p.add_subparsers(dest="command")

    p_cur = sub.add_parser("current", help="Show current conditions.")
    p_cur.add_argument("--raw", action="store_true", help="Print formatted current conditions (default).")
    p_cur.add_argument("--json", action="store_true", help="Dump the full API JSON used for current.")

    p_fc = sub.add_parser("forecast", help="Show forecast (daily + hourly).")
    p_fc.add_argument("--raw", action="store_true", help="Print formatted forecast text output (default).")
    p_fc.add_argument("--json", action="store_true", help="Dump the full forecast API JSON.")
    p_fc.add_argument("--daily", action="store_true", help="Show daily section only.")
    p_fc.add_argument("--hourly", action="store_true", help="Show hourly section only.")
    p_fc.add_argument("--days", type=int, default=10, help="How many daily entries to display (default: 10).")
    p_fc.add_argument("--hours", type=int, default=12, help="How many hourly entries to display (default: 12).")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()

    if not argv:
        parser.print_help()
        return 0

    args, extra = parser.parse_known_args(argv)
    if extra:
        return _print_error(f"unknown command '{extra[0]}'")

    try:
        api_key = _required_env("TEMPEST_API_KEY")
        station_id = _station_id()
    except Exception as e:
        return _print_error(str(e))

    cmd = args.command
    try:
        if cmd == "current":
            bf = _fetch_better_forecast(api_key, station_id)

            if getattr(args, "json", False):
                print(json.dumps(bf, indent=2, sort_keys=True))
                return 0

            lines = _render_current_from_better_forecast(bf)
            print("The current conditions at your house are:")
            print("\n".join(lines))
            return 0

        if cmd == "forecast":
            bf = _fetch_better_forecast(api_key, station_id)

            if getattr(args, "json", False):
                print(json.dumps(bf, indent=2, sort_keys=True))
                return 0

            daily_only = bool(getattr(args, "daily", False))
            hourly_only = bool(getattr(args, "hourly", False))
            show_daily = True
            show_hourly = True
            if daily_only and not hourly_only:
                show_hourly = False
            elif hourly_only and not daily_only:
                show_daily = False

            days_n = max(0, int(getattr(args, "days", 10)))
            hours_n = max(0, int(getattr(args, "hours", 12)))

            lines = _render_forecast_text(
                bf,
                show_daily=show_daily,
                show_hourly=show_hourly,
                days_n=days_n,
                hours_n=hours_n,
            )
            print("The forecast at your house is:")
            print("\n".join(lines))
            return 0

        return _print_error(f"unknown command '{cmd}'")

    except requests.Timeout:
        return _print_error("request timed out")
    except requests.HTTPError as e:
        return _print_error(f"http error: {e}")
    except Exception as e:
        return _print_error(str(e))


if __name__ == "__main__":
    raise SystemExit(main())