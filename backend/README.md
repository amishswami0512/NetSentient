# Semantic Router API (Flask backend)

Central Flask backend for the **Semantic Network Router** hackathon
prototype. Classifies simulated network traffic by semantic importance,
assigns a priority score, and demonstrates how "semantic routing"
protects high-priority traffic (emergency alerts, critical sensor data)
during simulated network congestion — while a baseline/fair allocation
mode treats everything equally and degrades badly under load.

This is a **prototype for a live demo**, not production telecom
infrastructure. State is in-memory and resets when Flask restarts.

## 1. Project Overview

- Frontend/dashboard team consumes this API over HTTP (JSON).
- AI/classification teammate will eventually replace the temporary
  rule-based classifier behind `POST /api/classify` (see
  "How Teammates Should Integrate" below).
- Networking/simulation teammate drives congestion/simulation via
  `POST /api/simulation/*`.
- Everything is deterministic — no random numbers — so the same
  sequence of calls always produces the same demo results.

## 2. Architecture

```
backend/
├── app.py                       # Flask app factory, blueprint registration, error handlers
├── config.py                    # Centralized config: priority map, CORS origins, limits
├── requirements.txt
├── .env.example
├── README.md
│
├── routes/                      # HTTP layer only — parses request, calls a service, returns JSON
│   ├── health.py                 GET /api/health
│   ├── traffic.py                 GET /api/network/status, GET/POST /api/traffic
│   ├── classify.py                POST /api/classify
│   ├── simulation.py              POST /api/simulation/*
│   └── demo.py                    POST /api/demo/*
│
├── services/                    # Business logic — no Flask imports here
│   ├── state_service.py          In-memory state manager (traffic, congestion, routing flag)
│   ├── classifier_service.py     Swappable classification abstraction
│   ├── routing_service.py        Priority-aware latency/loss/delivery metrics
│   └── simulation_service.py     Orchestrates state + routing into API-shaped results
│
├── models/
│   └── schemas.py               Request validation helpers + shared APIError type
│
└── tests/
    ├── test_health.py
    ├── test_traffic.py
    ├── test_classify.py
    ├── test_simulation.py
    └── test_demo.py
```

Design rules followed throughout:
- Routes never touch state directly or contain business logic — they
  call a service and serialize the result.
- All priority numbers live in **one place**: `config.PRIORITY_MAP`.
- All mutable demo state lives in **one place**: `services.state_service.state`.

## 3. Installation

Requires Python 3.11+.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optional, defaults work out of the box
```

## 4. Running the Server

```bash
python app.py
```

Server starts on `http://localhost:5000` by default. You should see
Flask's startup banner in the console.

## 5. Environment Variables

All optional — see `.env.example`. Copy it to `.env` to override defaults.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Port the dev server listens on |
| `HOST` | `0.0.0.0` | Bind address |
| `FLASK_DEBUG` | `true` | Enables Flask debug/auto-reload |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated CORS allow-list for the frontend |
| `MAX_CONTENT_LENGTH_BYTES` | `65536` | Max accepted request body size |

**CORS note:** `ALLOWED_ORIGINS` is never `*`. If your dashboard runs on
a different port, add it to this list (comma-separated) in your `.env`.

## 6. API Documentation / Frontend Integration

Base URL (local dev): `http://localhost:5000`

All responses are JSON. All errors follow this shape:

```json
{ "error": { "code": "INVALID_REQUEST", "message": "human readable reason" } }
```

| Method | Endpoint | Purpose | Request Body | Success Response |
|---|---|---|---|---|
| GET | `/api/health` | Liveness check | — | `{"status":"ok","service":"semantic-router-api","version":"1.0.0"}` |
| GET | `/api/network/status` | Current simulated network state | — | `{"congestion":bool,"load_percent":int,"bandwidth_mbps":float,"semantic_routing_enabled":bool,"active_connections":int,"timestamp":str}` |
| GET | `/api/traffic` | List active traffic with live metrics | — | `{"traffic":[{...}]}` |
| POST | `/api/traffic` | Create a traffic flow | `{"type":"emergency","label":"optional"}` | `201` created traffic item incl. metrics |
| POST | `/api/classify` | Classify free-text input | `{"input":"some text"}` | `{"category":str,"confidence":float,"priority":int}` |
| POST | `/api/simulation/congestion` | Toggle congestion | `{"enabled":bool}` | `{"congestion":bool,"load_percent":int,"bandwidth_mbps":float}` |
| POST | `/api/simulation/semantic-routing` | Toggle semantic routing | `{"enabled":bool}` | `{"semantic_routing_enabled":bool}` |
| POST | `/api/simulation/run` | Run one deterministic simulation step | — | `{"simulation_id":str,"network":{...},"results":[{...}]}` |
| POST | `/api/simulation/reset` | Reset all state to clean defaults | — | `{"status":"reset","network":{...},"traffic":[]}` |
| POST | `/api/demo/reset` | Seed the standard demo scenario | — | `{"traffic":[...],"network":{...}}` |
| POST | `/api/demo/congest` | Enable congestion + run simulation | — | `{"simulation_id":str,"network":{...},"results":[...]}` |
| POST | `/api/demo/compare` | Baseline vs. semantic routing comparison | — | `{"baseline":[...],"semantic":[...],"improvement":[...]}` |

Traffic `type` must be one of: `emergency`, `critical_sensor`, `video`,
`file`, `background`. Any other value returns `400 INVALID_REQUEST`.

Traffic items and simulation results include a computed `status` field
(`normal`, `protected`, `degraded`, `throttled`, `fair`) useful for
color-coding the dashboard — treat it as informational, additive to the
documented contract fields.

### Example requests

```bash
curl http://localhost:5000/api/health

curl -X POST http://localhost:5000/api/traffic \
  -H "Content-Type: application/json" \
  -d '{"type": "emergency", "label": "Ambulance emergency alert"}'

curl -X POST http://localhost:5000/api/classify \
  -H "Content-Type: application/json" \
  -d '{"input": "Critical heart rate anomaly detected"}'

curl -X POST http://localhost:5000/api/simulation/congestion \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

curl -X POST http://localhost:5000/api/simulation/semantic-routing \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

curl -X POST http://localhost:5000/api/simulation/run

curl -X POST http://localhost:5000/api/demo/reset
curl -X POST http://localhost:5000/api/demo/congest
curl -X POST http://localhost:5000/api/demo/compare
```

### Example error response

```bash
curl -X POST http://localhost:5000/api/traffic \
  -H "Content-Type: application/json" -d '{"type": "not_a_type"}'
```
```json
{"error":{"code":"INVALID_REQUEST","message":"Field 'type' must be one of: emergency, critical_sensor, video, file, background."}}
```

## 7. Semantic Priority

Centralized in `config.py`:

```python
PRIORITY_MAP = {
    "emergency": 10,
    "critical_sensor": 9,
    "video": 5,
    "file": 2,
    "background": 1,
}
```

- **Semantic routing ON + congestion:** delivery is interpolated by
  priority — emergency stays near ~98% delivered, background drops to
  ~5%. High priority is clearly protected.
- **Semantic routing OFF + congestion:** every traffic type gets the
  same "fair share" degraded service (~55-65% delivery) regardless of
  priority — this is the "before" picture for the demo.
- **No congestion:** everything gets good service (~97-99.5% delivery)
  regardless of routing mode, since there's nothing to prioritize.

`POST /api/demo/compare` runs both modes side-by-side (without touching
real state) so the frontend can render a clear before/after chart for
judges.

## 8. Demo Workflow

For a live demo, this sequence tells a complete story:

```bash
curl -X POST http://localhost:5000/api/demo/reset     # clean slate, 4 traffic flows, no congestion
curl -X POST http://localhost:5000/api/demo/compare    # show baseline vs semantic side by side
curl -X POST http://localhost:5000/api/demo/congest    # trigger congestion, show semantic routing protecting emergency traffic live
curl -X POST http://localhost:5000/api/simulation/reset  # back to clean state if you want to re-run
```

## 9. Testing

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

All tests use Flask's test client and reset in-memory state before and
after each test (`tests/conftest.py`), so they don't depend on the
server being started separately and don't leak state between runs.

## 10. How Teammates Should Integrate

**Frontend (dashboard):** point your HTTP client at `http://localhost:5000`,
allow-list your dev server's origin in `ALLOWED_ORIGINS`, and build
against the table in section 6. The API contract (endpoint names + JSON
field names) is stable — new fields may be added, existing ones won't be
renamed or removed without discussion.

**AI/classification teammate:** the `POST /api/classify` route
(`routes/classify.py`) only calls `classifier_service.classify_text()`.
To plug in a real model, implement `BaseClassifier.classify(text) ->
(category, confidence)` in `services/classifier_service.py` and call
`set_classifier(YourClassifier())`. Nothing else in the codebase needs
to change, and the response shape (`category`/`confidence`/`priority`)
stays the same.

A real implementation is already wired in: `GeminiClassifier` calls
Google's Gemini API (ported from the "HackyWacky" prototype) and maps
its 4 severity tiers onto our 5 categories. It activates automatically
when `GEMINI_API_KEY` is set in `.env` — with no key, `POST
/api/classify` keeps using the deterministic `RuleBasedClassifier`, so
nothing breaks if the key isn't configured. It also falls back to
`RuleBasedClassifier` on any Gemini API error (bad key, rate limit,
network issue, malformed response), so a live demo never crashes
because of an external API hiccup. Set `model="..."` in the
`GeminiClassifier(client, model=...)` call in `_build_default_classifier()`
if you want a different Gemini model.

**Networking/simulation teammate:** `services/routing_service.py` is
where congestion behavior is computed (`compute_metrics`). The
simulation is intentionally deterministic (no `random` calls) so a live
demo is reproducible — if you extend it, keep it that way.

## 11. Known Limitations

- State is in-memory and per-process: restarting Flask wipes all
  traffic/congestion/routing state. Use `POST /api/simulation/reset` or
  `POST /api/demo/reset` instead of restarting when you just need a
  clean slate.
- Single-process, no persistence, no auth — by design, for a 36-hour
  hackathon demo, not production use.
- The rule-based classifier in `classifier_service.py` is a deterministic
  keyword matcher, a placeholder for a real model.
- Metrics (latency/packet loss/delivery) are computed with simple,
  deterministic formulas tuned to look realistic for a demo — they are
  not derived from real network simulation.
