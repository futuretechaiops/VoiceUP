FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --no-cache-dir .
USER 10001
EXPOSE 8000
CMD ["uvicorn", "concierge.main:app", "--host", "0.0.0.0", "--port", "8000"]

