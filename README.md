# Tempest CLI (WeatherFlow/Tempest)

Professional, single-file CLI for retrieving station weather from the Tempest **better_forecast** endpoint.

This README is written for:
- Engineers integrating `tempest-cli` into AI systems and toolchains
- AI agents that must call and parse `tempest-cli` reliably

## 1) What This Tool Guarantees

- Stable command surface (`current`, `forecast`)
- Forced API units (no downstream unit guessing)
- Predictable plain-text output for `--raw`
- Raw passthrough JSON for `--json`
- Explicit error messages on configuration/network/API failures

## 2) Runtime Requirements

- Python 3.9+
- `requests`
- Optional: `python-dotenv` (only used if installed)

Environment variables:

- `TEMPEST_API_KEY` (required)
- `TEMPEST_STATION_ID` (required)
- `TEMPEST_TIMEOUT_S` (optional, default `8`)

If `python-dotenv` is available, the CLI attempts to load:

- `~/.openclaw/.env`

Example `.env`:

```bash
TEMPEST_API_KEY=your_token_here
TEMPEST_STATION_ID=161526
TEMPEST_TIMEOUT_S=8
```

## 3) Installation / Invocation

From this directory, run directly:

```bash
python tempest-cli.py --help
```

Executable in `~/bin`:

```bash
mkdir -p ~/bin
cat > "$HOME/bin/tempest-cli" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="$HOME/.openclaw/.env"
if [[ -f "$ENV_FILE" ]]; then
	set -a
	source "$ENV_FILE"
	set +a
fi

PY="${OPENCLAW_PY:-python3}"
TOOL="$HOME/.openclaw/tools/tempest/tempest-cli.py"

exec "$PY" "$TOOL" "$@"
EOF
chmod +x "$HOME/bin/tempest-cli"
```

Verify:

```bash
which tempest-cli
tempest-cli --help
```

### Existing wrapper in `~/bin/tempest-cli`

Current local wrapper behavior (if you use that executable):

- It is a Bash launcher.
- It sources `~/.openclaw/.env` when present.
- It runs `OPENCLAW_PY` if set, otherwise `python3`.
- It executes `~/.openclaw/tools/tempest/tempest-cli.py`.

If your repository path differs from `~/.openclaw/tools/tempest`, update the wrapper `TOOL` path accordingly.

## 4) Command Interface (Contract)

```text
tempest-cli current  [--raw|--json] [--timeout N]
tempest-cli forecast [--raw|--json] [--daily|--hourly] [--timeout N]
```

Important behavior:

- Global flags can be placed before **or after** the subcommand.
- `--json` always returns full API JSON and bypasses text formatting.
- `forecast` default mode prints **both** daily and hourly sections.
- `forecast --daily` prints only daily section.
- `forecast --hourly` prints only hourly section.

## 5) Output Modes

### Default mode (human-friendly preface)

- `current`: first line is `The current conditions at your house are:`
- `forecast`: first line is `The forecast at your house is:`

### `--raw` mode (AI integration recommended)

- No prose preface
- Structured line output from parser functions

### `--json` mode

- Raw API response, pretty-printed JSON

## 6) Text Output Shape (Current Implementation)

The exact set of lines can vary with missing API fields, but formatting follows these templates.

### `current --raw`

Typical lines (order preserved by implementation):

```text
Cond <conditions>
Temp <n.n>°
FeelsLike <n.n>°
Wind <DIR> <avg> G <gust> mph
Humidity <n>%
Pressure <n.nn> inHg
Precip <n.nn> in
UV (index) <n>
SolarRad <n> W/m^2
Brightness <n> lux
Sunrise <h:mm AM/PM>
Sunset <h:mm AM/PM>
Updated <h:mm:ss AM/PM  m/d/YYYY>
```

Notes:
- `Updated` in `current` has **no colon** after `Updated`.
- Sunrise/sunset use fallback discovery if missing from `current_conditions`.

### `forecast --raw` (default: both sections)

```text
Daily:
<Day dd>  Hi <n>° - Lo <n>°, <Conditions>[, <PrecipType p%>|Precip][, Sunrise ...][, Sunset ...]
...

Hourly:
<Day> <h AM/PM> <temp>° [FeelsLike <n>°] [Precip <n.nn> in] [<wind> mph] [<dir>], <Conditions>[, <PrecipType p%>|Precip]
...
Updated: <h:mm:ss AM/PM  m/d/YYYY>
```

Notes:
- Daily count: up to 10 rows.
- Hourly count: up to 12 rows.
- `Updated:` in forecast **includes a colon**.
- If `precip_probability <= 0`, text token is `Precip`.

## 7) API and Units

Endpoint used:

- `https://swd.weatherflow.com/swd/rest/better_forecast`

Query forces units to:

- Temperature: Fahrenheit (`units_temp=f`)
- Wind: mph (`units_wind=mph`)
- Pressure: inHg (`units_pressure=inhg`)
- Precipitation: inches (`units_precip=in`)
- Distance: miles (`units_distance=mi`)

## 8) Error Behavior

Failures terminate process with a readable error message (non-zero exit):

- Missing env vars
- HTTP timeout
- HTTP status failure
- JSON shape/parse or unknown fetch exception

Examples:

```text
error: missing required env var TEMPEST_API_KEY
error: Tempest request timed out after 8.0s
error: Tempest HTTP error: ...
error: Tempest fetch failed: <Type>: <message>
```

## 9) Integration Guidance for AI Tools

Recommended mode for machine consumption:

- Use `--raw` for line-based parsing
- Use `--json` when you need complete source fields

Suggested execution pattern:

1. Call with explicit timeout: `--timeout 8` (or environment default)
2. Capture stdout and exit code
3. On non-zero exit, surface stderr as tool error
4. Do not infer units; trust forced API unit contract

## 10) AI Parser Spec (Strict Pass)

Use this when implementing deterministic parsing from `--raw`.

### 10.1 Top-level section grammar

- `current --raw`:
	- No section header
	- Ends with `Updated <timestamp>`
- `forecast --raw` default:
	- Starts with `Daily:`
	- Contains a blank separator line
	- Then `Hourly:`
	- Ends with `Updated: <timestamp>`
- `forecast --daily --raw`:
	- `Daily:` rows + final `Updated: ...`
- `forecast --hourly --raw`:
	- `Hourly:` rows + final `Updated: ...`

### 10.2 Line classifiers (recommended regexes)

Timestamp token used by both updated lines:

```regex
([1-9]|1[0-2]):[0-5][0-9]:[0-5][0-9]\s(?:AM|PM)\s{2}(?:[1-9]|1[0-2])/(?:[1-9]|[12][0-9]|3[01])/\d{4}
```

Current updated line:

```regex
^Updated\s+<STAMP>$
```

Forecast updated line:

```regex
^Updated:\s+<STAMP>$
```

Daily row (tolerant):

```regex
^[A-Z][a-z]{2}\s+[0-9]{1,2}\s{1,}((Hi\s+-?\s*[0-9]+°\s+-\s+Lo\s+-?\s*[0-9]+°)|(Lo\s+-?\s*[0-9]+°)|())?,?\s*.*$
```

Hourly row (tolerant):

```regex
^[A-Z][a-z]{2}\s+([1-9]|1[0-2])\s(?:AM|PM)\s+[-0-9]+°.*,
```

Practical approach:

1. Classify by anchors first: `Daily:`, `Hourly:`, `Updated`, `Updated:`.
2. For non-anchor lines, branch by command context (`current` vs `forecast`).
3. Parse tokens left-to-right, treating optional groups as nullable:
	 - `FeelsLike`
	 - `Precip <amount> in`
	 - wind speed and direction
	 - precip descriptors appended to condition text

### 10.3 Stability notes

- Numeric precision is implementation-defined by formatter:
	- temps: usually integer in forecast, one decimal in current
	- precip amount: two decimals
- Optional lines can be omitted when source fields are missing.
- Do not hard-fail if condition text changes (free-form API text).

## 11) Non-Goals / Scope

- No local icon asset mapping (API returns icon tokens only)
- No package/distribution scaffolding; single script by design
- No write/update operations against Tempest APIs

## 12) Quick Verification

```bash
python tempest-cli.py current --raw
python tempest-cli.py forecast --daily --raw
python tempest-cli.py forecast --hourly --raw
python tempest-cli.py forecast --json
```