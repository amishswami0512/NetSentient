FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_DEBUG=false
EXPOSE 5000

# gunicorn, not `python app.py`: Flask's dev server is single-threaded
# and explicitly not meant to be exposed beyond localhost. 4 workers is
# a reasonable default for a small deployment -- tune with --workers
# for your actual load. State (SQLite, see Config.STATE_DB_PATH) and
# pcap captures (Config.CAPTURES_DIR) live under /app/data -- mount
# that as a volume so they survive a container restart.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "30", "app:app"]
