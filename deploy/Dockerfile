# Production image: API + chat widget bundle + headless Chromium (the crawler needs it to read
# JavaScript-built sites such as ones made with Lovable). Build from the repository root:
#   docker build -f deploy/Dockerfile -t voiceup .
FROM node:22-slim AS widget
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/widget/package.json apps/widget/
RUN npm ci --workspace @concierge/widget --include-workspace-root
COPY apps/widget apps/widget
RUN npm run build:embed --workspace @concierge/widget

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY services/api/pyproject.toml services/api/alembic.ini ./
COPY services/api/alembic ./alembic
COPY services/api/src ./src
RUN pip install --no-cache-dir ".[crawl]" \
 && playwright install --with-deps chromium \
 && chmod -R a+rX /ms-playwright
COPY --from=widget /repo/apps/widget/dist-embed/widget.js ./static/widget.js
RUN useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "concierge.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
