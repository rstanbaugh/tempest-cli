# Tempest CLI

A single-file command-line tool for retrieving **current conditions** and **forecast data** from a Tempest (WeatherFlow) weather station.

This tool is designed to:

- Run locally as a deterministic CLI  
- Be called by OpenClaw skills  
- Produce stable, predictable stdout  
- Contain all business logic (no logic in skills)  

All output is normalized to:

- Temperature → °F  
- Wind → mph  
- Pressure → inHg  
- Precipitation → inches  
- Distance → miles  

---

# Repository Structure

Recommended location:

~/.openclaw/workspace/tools/tempest

Files:

- tempest-cli.py  
- README.md  
- .gitignore  

This repository contains only the CLI tool.  
No wrapper files are stored here.

---

# Installation

## 1) Create a wrapper in ~/bin

```
ENV_FILE="$HOME/.openclaw/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi
PY="${OPENCLAW_PY:-python3}"
```

## 2) Make the CLI executable

chmod +x ~/.openclaw/workspace/tools/tempest/tempest-cli.py

## 3) ~/bin as the first entry in PATH.

Execute from anywhere:

tempest-cli current  
tempest-cli forecast  

---

# Wrapper Explanation

~/bin/tempest-cli is a symbolic link pointing to:

~/.openclaw/workspace/tools/tempest/tempest-cli.py

This design:

- Keeps the source version-controlled  
- Avoids hard-coded Python interpreter paths  
- Allows updating the tool without touching ~/bin  
- Keeps machine-specific configuration out of Git  

The wrapper is not committed to the repository because it contains a user-specific absolute path and lives outside the repo root.

---

# Required Environment Variables

These must be set in your environment.

Recommended location:

~/.openclaw/.env

Minimum required:

TEMPEST_API_KEY=your_api_key_here

Recommended:

TEMPEST_STATION_ID=161526

If forecast requires token-based access in your account:

TEMPEST_TOKEN=your_token  
TEMPEST_DEVICE_ID=your_device_id  

Optional:

TEMPEST_BASE_URL=https://swd.weatherflow.com  

---

# Usage

## Current Conditions

tempest-cli current

Example output:

The current conditions at your house are:  
Temperature: 51.1 °F  
Wind: 7 mph N  
Humidity: 60 %  
Pressure: 29.82 inHg  
Precipitation: 0.00 in  
Sunrise: 7:10 AM  
Sunset: 6:21 PM  
Updated: 3:00:29 PM  2/28/2026  

Raw mode (no header):

tempest-cli current --raw  

JSON mode:

tempest-cli current --json  

---

## Forecast

tempest-cli forecast  

Default behavior:

- Shows Daily section  
- Shows Hourly section  
- Updated timestamp is always the last line  

Daily only:

tempest-cli forecast --daily  

Hourly only:

tempest-cli forecast --hourly  

Limit output:

tempest-cli forecast --days 10 --hours 12  

Raw output:

tempest-cli forecast --raw  

JSON output:

tempest-cli forecast --json  

---

# Output Guarantees

- Updated: is always the final line.  
- No debug markers.  
- Raw mode emits only data lines.  
- JSON mode emits the complete API response.  

This makes the tool safe for OpenClaw skills that return stdout verbatim.

---

# Git Workflow

Initialize locally:

cd ~/.openclaw/workspace/tools/tempest  
git init  
git add .  
git commit -m "Initial Tempest CLI"  

Then create a remote repository and push:

git remote add origin git@github.com:<yourname>/tempest-cli.git  
git push -u origin main  

---

If anything in this still isn’t formatted the way you want for GitHub rendering, tell me exactly what you want changed and I’ll adjust it — cleanly and once.