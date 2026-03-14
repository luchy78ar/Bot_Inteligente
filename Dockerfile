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

CMD python -c "from src.web_server import app; import threading; import time; t = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False, threaded=True), daemon=True); t.start(); print('Server started'); time.sleep(3600)"
