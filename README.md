# NetSentient

Semantic Network Router prototype — classifies simulated network traffic
by semantic importance and prioritizes it during simulated congestion.

Backend/API: see [`backend/README.md`](backend/README.md) for setup, the
full API contract, and the demo workflow.

## Run the dashboard

Install the backend dependencies, then start Flask from the repository root:

```powershell
cd backend
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. Flask serves the frontend and API from the same
origin, so no separate frontend server or CORS setup is needed for the default
configuration.