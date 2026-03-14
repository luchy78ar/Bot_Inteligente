FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data logs

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-c", "
from src.web_server import app
import threading
import time

# Start web server in background thread
def run_server():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False, threaded=True)

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

print('Web server started on port 8080')
print('Health check available at /health')

# Keep container running
while True:
    time.sleep(3600)
"]
