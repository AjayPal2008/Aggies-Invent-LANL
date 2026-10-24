# One container serves the API and both dashboards (used on its own by Render; behind nginx in docker-compose).
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY shared shared
COPY manager-dashboard manager-dashboard
COPY hire-dashboard hire-dashboard
WORKDIR /app/backend
ENV PORT=8000 WEB_CONCURRENCY=2 AUTO_SEED=false
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/ready', timeout=3)"
# Prepare the database once, then start several worker processes.
CMD ["sh", "-c", "python -m scripts.prestart && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --limit-concurrency 400 --timeout-keep-alive 5 --proxy-headers --forwarded-allow-ips='*'"]
