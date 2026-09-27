# Business Reports web app: builds the web pages, then runs the Python backend that serves them.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt
COPY mis_reports/ mis_reports/
COPY server/ server/
COPY config/ config/
COPY --from=web /web/dist web/dist
RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
# PORT is set by hosting services such as Render; 8000 otherwise
CMD ["sh", "-c", "exec uvicorn server.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
