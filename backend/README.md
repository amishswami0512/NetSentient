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
- **Gemini provides semantic understanding; this backend decides the
  final priority.** Traffic descriptions are analyzed by Google's
  Gemini API for urgency/consequence/latency-sensitivity/reliability,
  and a deterministic priority engine (not Gemini) converts that into
  a final 0-10 priority. Gemini never touches routing directly — see
  "Semantic Priority Engine" below.
- Networking/simulation teammate drives congestion/simulation via
  `POST /api/simulation/*`.
- Everything downstream of semantic analysis is deterministic — no
  random numbers — so the same sequence of calls always produces the
  same demo results. Gemini itself is called with `temperature=0.1`
  and a fixed `seed` to keep its output as stable as possible; the
  cache (see below) makes repeat inputs exactly reproducible regardless.

## 2. Architecture

```
backend/
├── app.py                       # Flask app factory, blueprint registration, error handlers
├── config.py                    # Centralized config: priority weights, category bounds, CORS, limits
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
│   ├── classifier_service.py     Deterministic keyword classifier (standalone + fallback's category detector)
│   ├── gemini_service.py         Raw Gemini call: structured JSON output, timeout, never raises
│   ├── semantic_service.py       Orchestrates: cache -> Gemini -> validation -> deterministic fallback
│   ├── priority_service.py       Deterministic priority engine: weighted formula + category safety bounds
│   ├── payload_cache.py          Generic LRU cache (fast-path for common/repeated payloads)
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
    ├── test_demo.py
    ├── test_payload_cache.py
    ├── test_gemini_service.py
    ├── test_semantic_service.py
    ├── test_priority.py
    └── test_fallback.py
```

The semantic → priority pipeline, end to end:

```
traffic text
  -> payload cache (instant on repeat input, any source)
  -> curated common-word fast path (instant, skips Gemini entirely)  [services/semantic_service.py: _COMMON_KEYWORD_SEED]
  -> Gemini semantic analysis (services/gemini_service.py)          [structured JSON, timeout-bounded]
  -> independent validation (services/semantic_service.py)          [Gemini output is untrusted]
  -> deterministic fallback if Gemini unavailable/invalid/timed out [services/classifier_service.py + config.FALLBACK_SEMANTIC_FACTORS]
  -> {category, confidence, urgency, consequence, latency_sensitivity, reliability_requirement}
  -> deterministic priority engine (services/priority_service.py)   [weighted formula + category safety bounds]
  -> final priority (0-10, continuous)
  -> network simulator (services/routing_service.py)                [Gemini never called here]
```

Design rules followed throughout:
- Routes never touch state directly or contain business logic — they
  call a service and serialize the result.
- Priority is **never** a flat function of category alone — see
  section 7. All weights/bounds live in **one place**: `config.py`.
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
| `GEMINI_API_KEY` | *(empty)* | Optional. If set, `POST /api/classify` and traffic creation use real Gemini semantic analysis. If unset, the deterministic fallback is used and the app works identically otherwise. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model used for semantic analysis (fast/cheap, appropriate for structured classification) |
| `GEMINI_TIMEOUT_SECONDS` | `12.0` | Hard cap on a single Gemini call before falling back. Must be >= 10 -- the Gemini API server rejects a shorter deadline outright regardless of API key validity |
| `API_KEYS` | *(empty)* | Comma-separated. If set, every `/api/*` route except `/api/health` requires `Authorization: Bearer <key>`. Unset means no auth. See section 14 |
| `ENFORCEMENT_ENABLED` | `false` | If true, `POST /api/enforce/apply` actually runs tc/iptables commands instead of a dry run. See section 9 |

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
| POST | `/api/classify` | Semantic analysis + priority for free-text input | `{"input":"some text"}` | `{"category":str,"confidence":float,"priority":float,"priority_factors":{...},"low_confidence":bool,"source":"gemini"\|"keyword"\|"fallback","reason":str}` |
| POST | `/api/simulation/congestion` | Toggle congestion | `{"enabled":bool}` | `{"congestion":bool,"load_percent":int,"bandwidth_mbps":float}` |
| POST | `/api/simulation/semantic-routing` | Toggle semantic routing | `{"enabled":bool}` | `{"semantic_routing_enabled":bool}` |
| POST | `/api/simulation/run` | Run one deterministic simulation step | — | `{"simulation_id":str,"network":{...},"results":[{...}]}` |
| POST | `/api/simulation/reset` | Reset all state to clean defaults | — | `{"status":"reset","network":{...},"traffic":[]}` |
| POST | `/api/demo/reset` | Seed the standard demo scenario | — | `{"traffic":[...],"network":{...}}` |
| POST | `/api/demo/congest` | Enable congestion + run simulation | — | `{"simulation_id":str,"network":{...},"results":[...]}` |
| POST | `/api/demo/compare` | Baseline vs. semantic routing comparison | — | `{"baseline":[...],"semantic":[...],"improvement":[...]}` |
| POST | `/api/capture/analyze` | Classify real traffic from a `.pcap` file | `{"pcap_path":"sample.pcap"}` | `{"flows_processed":int,"traffic":[{...,"flow_metadata":{...}}]}` |
| POST | `/api/enforce/apply` | Apply a priority to a real flow pattern via tc/iptables | `{"protocol":"tcp","port":443,"priority":8.7,"dst_cidr":"optional"}` | `{"tier":str,"fwmark":int,"dry_run":bool,"commands":[...],"applied":bool,"errors":[...]}` |
| GET | `/api/enforce/status` | Current tc/iptables enforcement state | — | `{"enabled":bool,"interface":str,"bandwidth_mbps":float,"tiers":[...],"qdisc":str\|null,"classes":str\|null,"mangle_rules":str\|null}` |
| POST | `/api/enforce/reset` | Tear down all enforcement rules | — | `{"interface":str,"dry_run":bool,"commands":[...],"applied":bool,"errors":[...]}` |

Traffic `type` must be one of: `emergency`, `critical_sensor`, `real_time`,
`video`, `file`, `background`. Any other value returns `400 INVALID_REQUEST`.

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
  -d '{"input": "Factory temperature exceeded dangerous threshold"}'
# ->
# {
#   "category": "critical_sensor",
#   "confidence": 0.94,
#   "priority": 8.9,
#   "priority_factors": {
#     "urgency": 0.92, "consequence": 0.95,
#     "latency_sensitivity": 0.88, "reliability_requirement": 0.93
#   },
#   "low_confidence": false,
#   "source": "gemini",
#   "reason": "Dangerous sensor condition requiring rapid response."
# }
# (with no GEMINI_API_KEY set, "source" is "fallback" and the factors
# come from config.FALLBACK_SEMANTIC_FACTORS for the detected category
# instead of a live semantic read of this specific description)

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
{"error":{"code":"INVALID_REQUEST","message":"Field 'type' must be one of: emergency, critical_sensor, real_time, video, file, background."}}
```

## 7. Semantic Priority Engine

**Priority is not a function of category alone.** Two `critical_sensor`
items can land anywhere from ~1.5 (routine reading) to ~9.5 (dangerous
threshold exceeded) depending on what the traffic actually describes.

### Semantic factors (each 0.0-1.0)

Extracted per traffic description by `services/semantic_service.py`
(Gemini, or the deterministic fallback):

| Factor | Question it answers |
|---|---|
| `urgency` | How quickly must this be delivered? |
| `consequence` | How bad is it if this is delayed or dropped? |
| `latency_sensitivity` | Does this need near-real-time delivery? |
| `reliability_requirement` | How important is guaranteed successful delivery? |

### Keyword fast path (cost/latency optimization)

Not every input needs a full Gemini call. `services/semantic_service.py`
keeps a small curated dictionary of common short words/phrases
(`_COMMON_KEYWORD_SEED`: "emergency", "software update", "video call",
etc.) that resolve instantly with `"source": "keyword"`, skipping
Gemini entirely.

This is deliberately a **curated list**, not "skip Gemini whenever any
keyword matches" — a broad keyword trigger would defeat the point of
Gemini for realistic input. "Routine temperature reading" and
"temperature exceeded dangerous threshold" both contain "temperature",
but only real semantic analysis can tell them apart; fast-pathing on
keyword presence alone would silently lose exactly the context-awareness
this whole engine exists to provide. Only genuinely unambiguous short
terms are in the seed list — anything more descriptive still goes to
Gemini (or the deterministic fallback if Gemini isn't available).

### The formula (`services/priority_service.py`, weights in `config.PRIORITY_WEIGHTS`)

```python
priority = 10 * (
    0.35 * urgency
  + 0.30 * consequence
  + 0.20 * latency_sensitivity
  + 0.15 * reliability_requirement
)
```

**These weights are a manually chosen starting policy, not a
machine-learned result.** They are honest, documented reasoning, kept
in `config.py` so they can be tuned after live testing without
touching code. Ordering: `urgency` (0.35) > `consequence` (0.30) >
`latency_sensitivity` (0.20) > `reliability_requirement` (0.15).
- `urgency` is weighted highest — how soon something must move is the
  most directly actionable signal for a network scheduler.
- `consequence` is weighted second — closely reinforces urgency (what
  happens if it's late), but alone is a slower-acting concern (e.g. a
  consequential-but-not-urgent scheduled safety check).
- `latency_sensitivity` is weighted third — needing near-real-time
  delivery matters, but real-time-ness alone doesn't imply importance
  (a casual video call is latency-sensitive but not high-stakes).
- `reliability_requirement` is weighted lowest — it's the factor most
  correlated with the other three already (urgent/consequential traffic
  usually also needs reliable delivery), so weighting it high would
  effectively double-count the same signal.

### Category safety bounds (`config.CATEGORY_PRIORITY_BOUNDS`)

A guardrail, not the primary mechanism — the raw formula above is
clamped into a `(min, max)` range per category so a single noisy or
hallucinated factor can't push e.g. `background` traffic to a 10, or
`emergency` traffic below a safe floor:

| Category | Bounds | Reasoning |
|---|---|---|
| `emergency` | (7.5, 10.0) | By definition must stay in the top safety tier regardless of factor noise |
| `critical_sensor` | (1.0, 10.0) | Genuinely spans routine to dangerous — bounds only prevent literal zero |
| `real_time` | (2.0, 8.5) | Interactive/control traffic is rarely background-level; top band reserved for true emergencies |
| `video` | (1.0, 7.5) | Ordinary streaming shouldn't outrank real emergencies |
| `file` | (0.3, 6.0) | Bulk transfers are rarely top-tier, but an "emergency patch" file can still be elevated |
| `background` | (0.0, 3.5) | Should never compete with anything time-sensitive, regardless of factor noise |

Within its bounds, the semantic factors still fully determine where an
item lands — the bounds only stop obviously-wrong outcomes at the edges.

### Confidence vs. priority

These measure different things and are never conflated: confidence is
"how certain is this classification", priority is "how important is
this traffic." Confidence is **never multiplied into priority**.
Instead, if confidence is below `config.LOW_CONFIDENCE_THRESHOLD`
(default `0.55`), the response is marked `low_confidence: true` and
priority is dampened conservatively — capped at the midpoint of
whatever category's bound range it landed in, so an uncertain guess
can never reach the top of that tier (and is never bumped to
emergency-level priority just because that happened to be the guess).

### Network simulation behavior

- **Semantic routing ON + congestion:** delivery is interpolated by
  priority — high-priority traffic stays well-protected, low-priority
  traffic is sacrificed. Because priority is now continuous, this is a
  smooth gradient, not 5 fixed tiers.
- **Semantic routing OFF + congestion:** every traffic type gets the
  same "fair share" degraded service regardless of priority — the
  "before" picture for the demo.
- **No congestion:** everything gets good service regardless of routing
  mode, since there's nothing to prioritize.

`POST /api/demo/compare` runs both modes side-by-side (without touching
real state) so the frontend can render a clear before/after chart for
judges. `services/routing_service.py` only ever consumes the final
`priority` number — it never calls Gemini and doesn't know semantic
analysis exists.

## 8. Real Traffic Ingestion (`POST /api/capture/analyze`)

Every other endpoint takes a hand-typed description. This one takes
**actual network traffic** you captured yourself and runs it through
the exact same `semantic_service` / `priority_service` pipeline — no
separate scoring logic, no toy data.

**How to try it with real traffic:**

```bash
# 1. Capture some real traffic on your own machine (needs sudo):
sudo tcpdump -i any -w sample.pcap -c 200

# 2. Drop it where the backend is allowed to read from:
mkdir -p backend/data/captures
cp sample.pcap backend/data/captures/

# 3. Analyze it:
curl -X POST http://localhost:5000/api/capture/analyze \
  -H "Content-Type: application/json" \
  -d '{"pcap_path": "sample.pcap"}'
```

What it does, in order (`services/capture_service.py`):
1. Reads the pcap with `scapy`, groups packets into flows by 5-tuple
   (both directions of a connection collapse to one flow).
2. Per flow, extracts what's actually observable: a TLS SNI hostname
   (parsed directly from the ClientHello's plaintext extension — no
   decryption involved, that field is never encrypted), a DNS query
   name, or falls back to protocol/port with a well-known-service
   name (`443` → "HTTPS/TLS", `53` → "DNS", etc.).
3. Turns that into a factual description, e.g. `"Encrypted TLS session
   to 'meet.google.com' on port 443, 340 packets / 210000 bytes over
   12.4s"` — never a guess at category or importance, just what was
   observed.
4. Feeds that description into `semantic_service.analyze()` — the
   identical function `/api/classify` uses — so real captured traffic
   is judged by the same Gemini/keyword/fallback rules as typed input.
5. Adds each flow as a real traffic entry (`state.add_captured_traffic`)
   so it shows up in `/api/traffic` and the dashboard like anything else.

**Constraints, on purpose:**
- `pcap_path` is resolved against `Config.CAPTURES_DIR`
  (`backend/data/captures/` by default) and rejected if it would
  escape that directory — this endpoint reads a file by client-supplied
  name, so path traversal is the obvious attack surface and is blocked
  at the route layer (`routes/capture.py::_resolve_capture_path`).
- Only the top `CAPTURE_MAX_FLOWS` flows by packet count are processed
  (default 25) — a huge pcap shouldn't turn one request into thousands
  of Gemini calls.
- `scapy` is an optional dependency, same pattern as `google-genai`:
  not installed → this one endpoint returns `501 CAPTURE_UNAVAILABLE`
  with a clear message, nothing else in the app is affected.
- Captured traffic can contain real hostnames/IPs from your own
  network — `backend/data/` (captures included) is gitignored, never
  commit a real `.pcap` file.

## 9. Real Enforcement (`POST /api/enforce/apply`)

Section 8 classifies real traffic. This is the other half: actually
shaping real bandwidth by priority, via `tc` (HTB queueing) and
`iptables` (fwmark packet marking) -- `services/enforcement_service.py`.

**Safe by default.** `Config.ENFORCEMENT_ENABLED` is `false` unless you
explicitly set it, and `Config.ENFORCEMENT_INTERFACE` defaults to `lo`
(loopback, never carries real traffic). Out of the box, every call
here is a **dry run**: it returns the exact `tc`/`iptables` commands it
would run without executing anything. This isn't a demo simplification
-- it's a real safety default, because enabling this reconfigures an
actual network interface, and that should never happen just because a
repo was cloned and `.env` copied without reading it.

```bash
curl -X POST http://localhost:5000/api/enforce/apply \
  -H "Content-Type: application/json" \
  -d '{"protocol": "tcp", "port": 443, "priority": 8.7}'
# -> {"tier":"critical","fwmark":10,"dry_run":true,"commands":[...],"applied":false,"errors":[]}
```

**How priority maps to bandwidth**, 4 fixed tiers off one bandwidth
budget (`ENFORCEMENT_BANDWIDTH_MBPS`), each with a guaranteed floor
(`rate`) and a max it may borrow when others are idle (`ceil`, HTB's
standard model):

| Priority | Tier | fwmark | Guaranteed | Max (borrowed) |
|---|---|---|---|---|
| ≥ 7.5 | critical | 10 | 50% | 90% |
| ≥ 5.0 | high | 20 | 25% | 60% |
| ≥ 2.0 | normal | 30 | 15% | 40% |
| < 2.0 | low | 40 | 5% | 15% |

**To actually shape real traffic** (verified working on a live
interface during development -- root + `NET_ADMIN` required):

```bash
export ENFORCEMENT_ENABLED=true
export ENFORCEMENT_INTERFACE=eth0   # your real interface -- NOT lo
python app.py
```

What happens on the first real `apply` call, in order:
1. **Base topology, once per process** (`tc qdisc replace ... htb` +
   one `tc class` per tier + one `tc filter` per tier). Uses the `u32`
   classifier matching on fwmark, not the more commonly-documented
   `fw` classifier -- `cls_fw` needs a kernel module that isn't present
   on every kernel (confirmed missing on at least one real deployment
   target), while `u32` is effectively universal on Linux.
2. **Per-flow mark rule** (`iptables -t mangle`, in a dedicated
   `NETSENTIENT_MARK` chain jumped to from `OUTPUT` -- never rules
   inserted directly into `OUTPUT`, so this never disturbs any
   pre-existing rules on a real box). Idempotent via an `iptables -C`
   check before every `-A`, so repeated calls (or a process restart)
   never pile up duplicate rules.

Subsequent calls only add their own mark rule -- the base topology is
skipped once already applied (`tc qdisc replace` on the root qdisc
would otherwise destroy and recreate the whole tree, including every
other tier's filter, on every single call).

`GET /api/enforce/status` shows the live `tc`/`iptables` state
(`tc -s qdisc/class show`, `iptables -t mangle -L`) for a demo.
`POST /api/enforce/reset` deletes the qdisc and flushes the mark chain
-- also a dry run unless `ENFORCEMENT_ENABLED=true`.

**Not yet wired up:** nothing currently calls `/api/enforce/apply`
automatically when `/api/capture/analyze` classifies a flow -- they're
separate endpoints today. Chaining them (auto-enforce every captured
flow's computed priority) is the natural next step once you're ready
to point this at a real interface.

## 10. Demo Workflow

For a live demo, this sequence tells a complete story:

```bash
curl -X POST http://localhost:5000/api/demo/reset     # clean slate, 5 descriptive traffic flows, no congestion
curl -X POST http://localhost:5000/api/demo/compare    # show baseline vs semantic side by side
curl -X POST http://localhost:5000/api/demo/congest    # trigger congestion, show semantic routing protecting emergency traffic live
curl -X POST http://localhost:5000/api/simulation/reset  # back to clean state if you want to re-run
```

## 11. Testing

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

All tests use Flask's test client and reset in-memory state before and
after each test (`tests/conftest.py`), so they don't depend on the
server being started separately and don't leak state between runs.

## 12. How Teammates Should Integrate

**Frontend (dashboard):** point your HTTP client at `http://localhost:5000`,
allow-list your dev server's origin in `ALLOWED_ORIGINS`, and build
against the table in section 6. The API contract (endpoint names + JSON
field names) is stable — new fields may be added, existing ones won't be
renamed or removed without discussion.

**AI/classification teammate:** semantic analysis is fully wired to
Gemini already (`services/gemini_service.py` + `services/semantic_service.py`).
Set `GEMINI_API_KEY` in `.env` to activate it — with no key, the system
runs entirely on the deterministic fallback, so nothing breaks if the
key isn't configured. Things you can safely tune without touching
anything else:
- The Gemini prompt/system instruction: `gemini_service.SYSTEM_INSTRUCTION`.
- The model: `GEMINI_MODEL` in `.env` (default `gemini-3.5-flash-lite`).
- The fallback's per-category typical factors: `config.FALLBACK_SEMANTIC_FACTORS`.
- The priority weights/bounds: `config.PRIORITY_WEIGHTS` / `config.CATEGORY_PRIORITY_BOUNDS`.

If you want to swap in a different classification approach entirely
(e.g. a trained model instead of Gemini), it only needs to conform to
`semantic_service.analyze(text) -> {category, confidence, factors, reason, source}`
— `routes/classify.py` and `priority_service.py` don't need to change.

**Networking/simulation teammate:** `services/routing_service.py` is
where congestion behavior is computed (`compute_metrics`). It only ever
consumes the final `priority` float — it never calls Gemini and has no
knowledge that semantic analysis exists. The simulation is intentionally
deterministic (no `random` calls) so a live demo is reproducible — if
you extend it, keep it that way.

## 13. Known Limitations

- Live SNI sniffing only sees a hostname for connections whose
  TLS/QUIC handshake happens *after* sniffing starts — a connection
  already established before the server started still falls back to
  reverse DNS until it reconnects. It also only ever helps with HTTPS
  (port 443); plain HTTP and other protocols were never affected by
  the reverse-DNS problem it fixes.
- QUIC decryption only supports version 1 (RFC 9001) and only Initial
  packets — a QUIC version negotiation, a non-v1 draft version, or any
  packet past the handshake is deliberately skipped, not a bug. A
  fragmented ClientHello only reassembles from fragments that arrive
  contiguously starting at offset 0; badly out-of-order fragments
  (rare in practice) fall back to reverse DNS instead of waiting
  indefinitely.
- State persists to a real SQLite database (`Config.STATE_DB_PATH`,
  WAL mode), safe across process restarts and multiple worker
  processes sharing the file. It's still a single-file database, not a
  networked multi-writer one like Postgres — appropriate at the scale
  this app runs at, not infinitely scalable. Use
  `POST /api/simulation/reset` or `POST /api/demo/reset` for an
  explicit clean slate.
- `Config.API_KEYS` gates every `/api/*` route except `/api/health`,
  but it's a single shared secret per key, not per-user auth/RBAC —
  fine for gating access to the API as a whole, not for multi-tenant
  access control.
- Gunicorn's worker-process model (see `Dockerfile`) means each worker
  has its own in-memory Gemini result cache (`services/semantic_service.py`'s
  `PayloadCache`) — the same classification can still be a genuine
  Gemini call in each of N workers before all of them have it cached,
  since the cache isn't shared across processes. A shared cache (e.g.
  Redis) would fix this but adds an external service dependency this
  project doesn't otherwise need; worth it at real production traffic
  volume, not implemented here.
- `POST /api/capture/analyze` and `POST /api/enforce/apply` exist
  side by side but aren't chained — classifying a captured flow
  doesn't automatically enforce it. See sections 8 and 9.
- Enforcement (`services/enforcement_service.py`) uses 4 fixed
  bandwidth tiers keyed off fwmark, not per-flow fairness within a
  tier — two `critical` flows share that tier's guaranteed rate rather
  than each getting their own guarantee.
- The deterministic fallback (used with no `GEMINI_API_KEY`, or when
  Gemini fails) can only estimate *typical* semantic factors for the
  category it detects via keyword matching — it genuinely cannot
  distinguish "routine" from "dangerous" within a category the way
  Gemini's contextual analysis can. This is a known, disclosed
  limitation of fallback mode, not a bug: every fallback response is
  marked `"source": "fallback"` so it's never mistaken for a real
  semantic read.
- The priority weights (`config.PRIORITY_WEIGHTS`) are a manually
  chosen starting policy, not learned from data — see section 7 for
  the documented reasoning. They're expected to be tuned after live
  testing.
- Metrics (latency/packet loss/delivery) are computed with simple,
  deterministic formulas tuned to look realistic for a demo — they are
  not derived from real network simulation.
- Gemini itself is not perfectly deterministic even at `temperature=0.1`
  with a fixed `seed` — true determinism for *repeated* inputs is
  guaranteed by the in-memory cache (`services/semantic_service.py`),
  not by Gemini's own consistency. A brand-new phrasing of the same
  underlying situation could, in principle, get a slightly different
  score from Gemini on different runs.

## 14. Production Deployment

**Auth.** Set `API_KEYS` (comma-separated) in `.env` and every
`/api/*` route except `/api/health` requires
`Authorization: Bearer <key>`. Unset (default) means no auth, same as
every earlier section of this README — set it before exposing the API
beyond localhost.

```bash
curl -X POST http://localhost:5000/api/classify \
  -H "Authorization: Bearer $YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "Ambulance emergency alert dispatched"}'
```

**Running it for real**, instead of `python app.py` (Flask's dev
server, single-threaded, not meant to be exposed beyond localhost):

```bash
# Directly with gunicorn:
pip install -r requirements.txt
FLASK_DEBUG=false gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 30 app:app

# Or with Docker:
docker compose up --build
```

The `Dockerfile`/`docker-compose.yml` mount `./data` as a volume, so
the SQLite state database and any pcap captures survive a container
restart. Real enforcement (`ENFORCEMENT_ENABLED=true` against a real
interface) needs the container to see and modify a real host
interface — `docker-compose.yml` has `network_mode: host` +
`cap_add: NET_ADMIN` commented out for exactly that case; it's off by
default because granting NET_ADMIN is a real capability grant, not
something a compose file should hand out silently.

Everything above was verified to actually run this way during
development: gunicorn with multiple workers serving real requests, and
the tc/iptables commands in section 9 executed against a live
interface — not just described.

## 15. Automatic Live Detection (open a site, it shows up)

Beyond the manual `POST /api/traffic/scan` (section 6), the server now
runs a background poller (`services/scan_poller.py`) that re-scans
your machine's real live network connections every
`SCAN_POLL_INTERVAL_SECONDS` (default 5s) and automatically adds any
genuinely new one as traffic — open YouTube, and within a few seconds
a new flow appears without calling any endpoint yourself. Dedup is
exact-label match against currently active traffic, so an ongoing
connection doesn't get re-added every tick. On by default
(`SCAN_POLL_ENABLED=true`) since it only reads local connection info,
never touches the network.

**The hostname problem, and how it's solved.** Reverse DNS (the
original approach) is unreliable for exactly the sites worth naming
correctly — verified directly, not assumed:

```
youtube.com     -> reverse-resolves to: ia-in-f91.1e100.net
googlevideo.com -> reverse-resolves to: yucbfrl-in-f99.1e100.net
```

Google-hosted services (YouTube, Gmail, Search, Drive) all sit behind
generic infrastructure hostnames like that, so a connection would show
up as `"...connection to ia-in-f91.1e100.net..."` with no signal
anywhere for Gemini or the fallback classifier to work with.

`services/live_sniff_service.py` fixes this by reading the real
hostname straight out of the TLS handshake's SNI field — the same
unencrypted field `capture_service.py`'s pcap analysis already reads,
just watched live on a real interface instead of parsed from a
recorded file. When available, it takes priority over reverse DNS in
`network_scan_service.py`. It's **off by default**
(`SNI_SNIFF_ENABLED=false`): unlike the connection poller, this needs
raw packet access — the same privilege level `tcpdump` needs (`sudo`
on Mac/Linux). Enable it with:

```bash
sudo SNI_SNIFF_ENABLED=true python3 app.py
```

Without it, or if it's enabled but scapy isn't installed, or the
process isn't running with the needed privileges: everything still
works exactly as before this existed, just back to reverse-DNS
hostnames. Nothing crashes either way.

**QUIC (HTTP/3) is also handled, not just plain TLS.** Modern Chrome
negotiates QUIC — HTTP/3 over UDP — by default with most Google
properties, YouTube included. Two things had to be fixed for that:

1. `network_scan_service.py`'s connection scan only matched
   `psutil.CONN_ESTABLISHED`, which UDP sockets never report — confirmed
   directly against a real UDP socket (`psutil` always reports UDP
   status as `CONN_NONE`, since UDP is connectionless), not assumed.
   Every QUIC connection was invisible to the scanner regardless of how
   active it was. Fixed: a UDP socket with a real remote address now
   counts too.
2. QUIC's Initial packets — the only ones carrying the ClientHello —
   are encrypted, but with keys derived entirely from public values (a
   fixed salt plus the packet's own visible connection ID, RFC 9001
   section 5.2), not a real secret. `live_sniff_service.py` decrypts
   them using `aioquic`, a well-tested, RFC 9001-compliant
   implementation, rather than hand-rolled crypto — **validated
   directly against the RFC's own official Appendix A.2 test vector
   before trusting it on live traffic** (bit-exact match, confirmed via
   a reference implementation's own test suite since the RFC mirrors
   this environment could reach were blocked by network policy). A
   fragmented ClientHello spanning multiple Initial packets (common for
   a real browser's full extension set) is reassembled from its CRYPTO
   frames before extraction.

Verified with genuine live packet capture, not just direct function
calls: a real UDP datagram carrying the RFC's own encrypted test
packet was sent on the wire, captured live by `scapy.sniff()`,
decrypted, and correctly yielded `"example.com"` — the same hostname
the RFC vector's ClientHello actually specifies.

QUIC decryption only covers Initial packets, which is inherent, not a
gap to fix — every later packet in a QUIC connection uses real
negotiated session keys this process has no way to obtain, by design
(that's the whole point of a handshake).

Both background threads guard against Flask's debug-mode reloader
running application setup twice (`WERKZEUG_RUN_MAIN` check in
`app.py`) — otherwise `FLASK_DEBUG=true` (the default) would start two
competing pollers/sniffers per process.
