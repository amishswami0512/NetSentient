# NetSentient

NetSentient is a prototype semantic network router. It takes a human-readable
description of a network flow, classifies how important that flow is, assigns
it a priority, and simulates what happens when network capacity becomes
constrained.

The project is designed to demonstrate one idea:

> Network traffic should be routed according to meaning and consequence, not
> only according to packet order or a flat fair-share policy.

This is a deterministic hackathon/demo project. It does not inspect real
packets, control a router, measure a real link, or provide production traffic
management.

## Current Status

The Flask backend and its API tests are the reliable part of the repository.
The checked-in frontend is an older dashboard shell and is currently **not
connected to the backend contract**: it calls `/metrics`, `/toggle_congestion`,
and `/toggle_qos`, while the backend exposes `/api/...` routes instead. As a
result, opening the HTML page can show fallback-looking numbers while no real
backend state is being displayed. Use the API examples below to exercise the
working implementation, or update the frontend client before presenting the
site as a complete live dashboard.

## What It Solves

In a congested network, treating every flow equally can waste scarce capacity
on traffic that can wait while safety-critical traffic is delayed. NetSentient
models a priority-aware alternative:

- Emergency traffic receives the highest priority.
- Critical sensor traffic is protected next.
- Video/communication traffic receives a middle priority.
- File transfers and background traffic can be degraded first.
- A baseline mode shows what happens when congestion ignores semantic priority.

The benefit is explanatory rather than operational: the simulation makes the
trade-off visible to a demo audience and gives an API boundary that could later
be connected to a real classifier, telemetry system, or network controller.

## How It Works

1. A client sends text to `POST /api/classify`, or creates a flow directly with
	 `POST /api/traffic`.
2. The classifier maps the text to one supported category and returns a
	 confidence value and fixed priority score.
3. The state service stores active flows, congestion state, and whether
	 semantic routing is enabled. This state exists only in the running Python
	 process.
4. The routing service calculates deterministic delivery percentage, latency,
	 packet loss, and status from priority plus network mode.
5. The simulation and demo routes expose the results and compare semantic
	 routing against a congestion baseline.

### Classification

Without a Gemini key, classification uses a deterministic keyword matcher. It
counts category keyword hits and breaks ties toward the higher-priority
category. Unknown text falls back to `background` with low confidence.

With `GEMINI_API_KEY`, the optional `GeminiClassifier` asks Google Gemini to
select one of four conceptual tiers, maps those tiers onto the API's traffic
categories, and falls back to the keyword classifier when the request fails or
returns invalid data.

The current category contract is:

| Category | Priority | Typical meaning |
|---|---:|---|
| `emergency` | 10 | Life safety, crisis, imminent failure |
| `critical_sensor` | 9 | Medical, industrial, or infrastructure sensor data |
| `video` | 5 | Video, calls, streaming, standard communication |
| `file` | 2 | Downloads, uploads, document or archive transfer |
| `background` | 1 | Updates, backups, synchronization, low-urgency work |

### Routing simulation

The simulation uses fixed values rather than real network measurements:

- Normal mode reports approximately 10 Mbps available and 30% load.
- Congested mode reports approximately 2 Mbps available and 82% load.
- With semantic routing enabled, congested delivery is interpolated from
	priority anchors: high-priority flows retain much higher delivery than bulk
	flows.
- With semantic routing disabled, all flows receive a roughly equal degraded
	delivery result regardless of meaning.

Latency and packet loss are derived from the simulated delivery percentage.
They should be read as illustrative metrics, not as measurements of a physical
network.

## Technology Stack

### Backend

- Python 3.11 or newer
- Flask 3.x for the HTTP API and application factory
- Flask-CORS for configured cross-origin requests
- `python-dotenv` for `.env` configuration
- `google-genai` as an optional Gemini client
- pytest for API and service tests

The backend uses Flask blueprints for route groups, plain Python services for
business logic, and an in-memory state object for the demo. There is no
database, queue, authentication layer, packet capture library, or deployment
server configuration.

### Frontend

- Static HTML
- Tailwind CSS loaded from the Tailwind CDN
- Chart.js loaded from jsDelivr
- Vanilla JavaScript

The current frontend is a legacy prototype shell and requires integration work
to use the current API. It is not bundled, transpiled, or served by Flask.

## Repository Layout

```text
NetSentient/
├── README.md
├── backend/
│   ├── app.py                 Flask application factory and error handlers
│   ├── config.py              priorities, defaults, CORS, limits
│   ├── requirements.txt       Python dependencies
│   ├── models/schemas.py      JSON validation and API errors
│   ├── routes/                HTTP endpoints
│   ├── services/              classification, state, routing, simulation
│   └── tests/                 pytest coverage for the API and services
└── frontend/
		├── index.html             static dashboard markup
		└── app.js                 legacy frontend client
```

## Run the Backend

From PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

The API listens on `http://127.0.0.1:5000` by default. The command must be
run from `backend/`, because `app.py` is located there. The root of the
repository does not currently serve the frontend.

Check that the backend is alive:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/api/health
```

## API Endpoints

All API responses are JSON. Validation and routing failures use this shape:

```json
{"error":{"code":"INVALID_REQUEST","message":"human readable reason"}}
```

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness and version |
| `GET` | `/api/network/status` | Congestion, bandwidth, routing flag, active connection count |
| `GET` | `/api/traffic` | Active flows with calculated metrics |
| `POST` | `/api/traffic` | Add a flow; body: `{"type":"emergency","label":"optional"}` |
| `POST` | `/api/classify` | Classify text; body: `{"input":"..."}` |
| `POST` | `/api/simulation/congestion` | Set congestion; body: `{"enabled":true}` |
| `POST` | `/api/simulation/semantic-routing` | Set semantic routing; body: `{"enabled":true}` |
| `POST` | `/api/simulation/run` | Run one simulation step |
| `POST` | `/api/simulation/reset` | Clear state and restore defaults |
| `POST` | `/api/demo/reset` | Seed one flow for each demo category |
| `POST` | `/api/demo/congest` | Enable congestion and run a step |
| `POST` | `/api/demo/compare` | Compare baseline and semantic results |

Example workflow:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
Invoke-RestMethod -Method Post http://127.0.0.1:5000/api/demo/reset
Invoke-RestMethod -Method Post http://127.0.0.1:5000/api/demo/compare
Invoke-RestMethod -Method Post http://127.0.0.1:5000/api/demo/congest
Invoke-RestMethod http://127.0.0.1:5000/api/traffic
```

## Configuration

Copy `backend/.env.example` to `backend/.env` when overrides are needed.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Flask port |
| `HOST` | `0.0.0.0` | Bind interface |
| `FLASK_DEBUG` | `true` | Development reload and debug behavior |
| `ALLOWED_ORIGINS` | localhost ports 3000 and 5173 | CORS allow-list |
| `MAX_CONTENT_LENGTH_BYTES` | `65536` | Maximum request body size |
| `GEMINI_API_KEY` | empty | Enables the optional Gemini classifier |

Never commit a real Gemini key. If a key has been exposed in a repository,
revoke it and create a replacement.

## Testing

From the repository root:

```powershell
python -m pytest backend/tests
```

The tests use Flask's test client and reset process-local state between tests;
they do not require the server to be running. Gemini-dependent tests should be
run with a controlled key or mocked client. A live key can make classification
tests nondeterministic and can also cause network calls during a test run.

## What Can Make It Not Work

- Starting with `python app.py` from the repository root fails because the
	file is under `backend/`.
- The frontend calls legacy endpoints that do not exist in the current Flask
	API, so its controls and live values do not represent backend state.
- Opening `frontend/index.html` directly may be affected by browser CORS or
	local-file restrictions; it also depends on internet access for Tailwind and
	Chart.js CDNs.
- The backend is not serving the frontend, so `http://127.0.0.1:5000/` is not
	the dashboard URL in the current source.
- A missing, invalid, rate-limited, or blocked Gemini key changes classification
	to the rule-based fallback. That fallback is safe for a demo but shallow.
- CORS rejects browser requests from origins not listed in `ALLOWED_ORIGINS`.
- Restarting Flask clears all traffic and simulation state.
- Debug mode and the built-in Flask server are unsuitable for production.
- Dependency installation can fail if Python, pip, or the selected virtual
	environment is not the one being used to run the server.

## What Can Make the Site Look Useless

These are product limitations, not just setup mistakes:

- The simulation invents bandwidth, latency, packet loss, and delivery values;
	it does not prove that a real network improved.
- There is no real packet interception, routing enforcement, QoS queue, or
	network-device integration.
- The in-memory state is single-process and disappears on restart, so it is
	not suitable for historical monitoring or multiple users.
- The current frontend/backend endpoint mismatch means the visible dashboard
	can be disconnected from the working API.
- The rule classifier relies on substring keywords and can misclassify vague,
	ambiguous, or adversarial text.
- Gemini output is external, potentially slow, rate-limited, costly, and not
	guaranteed to be available; the fallback may make the AI claim look stronger
	than the actual semantic understanding.
- The demo compares hand-tuned formulas, not two real routing algorithms.
- There is no authentication, authorization, audit trail, persistence, or
	multi-tenant isolation.

## Sensible Next Steps

1. Replace the legacy frontend client with calls to the current `/api/...`
	 routes, or serve a deliberately versioned frontend that matches the API.
2. Add integration tests that start the backend and exercise the browser flow.
3. Replace in-memory state with persistent storage and add user/session
	 boundaries if this becomes more than a demo.
4. Connect telemetry and a network control plane before making operational
	 performance claims.
5. Add authentication, rate limiting, structured logs, secret management, and
	 production WSGI hosting before deployment.
