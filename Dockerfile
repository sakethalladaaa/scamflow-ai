FROM node:24-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCAMFLOW_DATABASE_PATH=/data/scamflow.sqlite3
WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend/ ./backend/
RUN python -m pip install --no-cache-dir .
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health', timeout=2)"
CMD ["sh", "-c", "uvicorn backend.scamflow.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
