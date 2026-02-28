# Tempest Weather Skill

Fetches current observations from the Tempest Weather API.

## Requirements

- TEMPEST_API_KEY must be set in:
  - Process environment (preferred under launchd)
  - or ~/.openclaw/.env as fallback

## Behavior

- Uses a 5 second HTTP timeout
- Returns wind in knots (kts)
- Returns formatted summary text
- Makes exactly one API call per query

## Public API

- fetch_tempest_weather()
- handle_weather_query(query: str)

## Manual Test

From openclaw environment:

/opt/homebrew/Caskroom/miniforge/base/envs/openclaw/bin/python -c "
from tempest_skill import fetch_tempest_weather;
print(fetch_tempest_weather())
"