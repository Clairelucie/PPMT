# Image de l'API PPMT (C5) — déployable sur Google Cloud Run, Render, Railway…
FROM python:3.11-slim
WORKDIR /app
COPY api/requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY api/ ./api/
COPY data/ppmt.db ./data/ppmt.db
ENV PORT=8080 PPMT_DB=/app/data/ppmt.db
# PPMT_API_KEY doit être fournie à l'exécution (secret), ex. : docker run -e PPMT_API_KEY=... 
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
