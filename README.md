# Tempest CLI (WeatherFlow / Tempest)

A single-file command-line tool for retrieving **current conditions** and **forecast data** from a Tempest (WeatherFlow) weather station using the Better Forecast endpoint.

This tool is designed to:

- Run locally as a deterministic CLI
- Be called by OpenClaw skills
- Produce stable, predictable stdout
- Contain all business logic (no logic inside skills)

All output units are normalized to:

- Temperature → °F
- Wind → mph
- Pressure → inHg
- Precipitation → inches
- Distance → miles

---

# Repository Location

Recommended path:

~/.openclaw/workspace/tools/tempest

Primary file:

tempest-cli.py

This is a standalone executable Python script.

---

# Required Environment Variables

These must be set in your environment.

Recommended location:
~/.openclaw/.env  
(Loaded automatically if present)

Minimum required:

TEMPEST_API_KEY=your_api_key_here  
TEMPEST_STATION_ID=161526

Optional:

TEMPEST_TIMEOUT_S=8

Notes:

- TEMPEST_API_KEY is your Tempest personal access token.
- TEMPEST_STATION_ID is your physical station ID.
- No token-based auth is required beyond TEMPEST_API_KEY.
- The CLI only supports reading data from your own station.

---

# Installation (Wrapper in ~/bin)

This project intentionally does NOT install as a Python package.
Instead, we use a simple symlink wrapper in ~/bin.

Ensure ~/bin is first in your PATH.

From your OpenClaw machine:

mkdir -p ~/bin  
chmod +x "$HOME/.openclaw/workspace/tools/tempest/tempest-cli.py"  
ln -sf "$HOME/.openclaw/workspace/tools/tempest/tempest-cli.py" "$HOME/bin/tempest-cli"

Verify:

which tempest-cli  
tempest-cli --help

The wrapper (~/bin/tempest-cli) is a symlink and should NOT be committed to git.

---

# Usage

## Current Conditions

tempest-cli current  
tempest-cli current --raw  
tempest-cli current --json  

Default output includes:

- Temperature
- Wind Chill
- Wind
- Humidity
- Pressure
- Precipitation
- UV Index
- Sunrise
- Sunset
- Updated timestamp (always last line)

---

## Forecast

By default, forecast returns BOTH daily and hourly sections:

tempest-cli forecast  

tempest-cli forecast --raw  
tempest-cli forecast --json  

---

### Daily Only

tempest-cli forecast --daily  
tempest-cli forecast --daily --raw  
tempest-cli forecast --daily --json  

Daily output shows 10 days, labeled as:

Sat 28  
Sun 1  
Mon 2  
etc.

Each line formatted:

Sat 28: High 50° / Low 25° — Snow Likely

---

### Hourly Only

tempest-cli forecast --hourly  
tempest-cli forecast --hourly --raw  
tempest-cli forecast --hourly --json  

Hourly output shows 12 hours formatted as:

5 PM: 39° 7 mph N — Partly Cloudy

---

# Output Modes

Default:
Includes a descriptive first line such as:

The current conditions at your house are:  
The forecast at your house is:

--raw:
Removes the descriptive header.
Best mode for OpenClaw skills.

--json:
Prints the full raw API JSON response.

In all non-JSON modes:
The final line is always:

Updated: HH:MM:SS AM/PM  M/D/YYYY

---

# Design Decisions

- Single-file CLI
- No package structure required
- No __init__.py
- No token-based alternate auth
- No temperature re-conversion (API units are forced via query parameters)
- All formatting handled inside the CLI
- Skills should simply execute and return stdout

---

# Git Workflow

From the tempest directory:

cd ~/.openclaw/workspace/tools/tempest  
git init  
git add .  
git commit -m "Initial Tempest CLI"  

Then create a remote repo and push:

git remote add origin <your-repo-url>  
git push -u origin main  

Do NOT commit ~/bin/tempest-cli (the symlink wrapper).

---

# Philosophy

All custom logic belongs in CLI tools.  
OpenClaw skills should act only as orchestration layers that:

- Decide which tool to call
- Execute the CLI
- Return stdout directly

This keeps the system scalable and deterministic.