FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching, then bring in source.
COPY pyproject.toml ./
COPY app ./app
COPY static ./static
COPY schema.sql ./schema.sql
COPY migrations ./migrations

# Editable install (not a copy into site-packages): main.py resolves the
# static/, schema.sql, and migrations/ paths relative to its own __file__,
# so the package must keep living at /app/app for those relative lookups to
# work.
RUN pip install --no-cache-dir -e .

ENV BROLL_DATA_ROOT=/data
# BROLL_INGEST_TOKEN and BROLL_SHARES are expected to be provided at deploy
# time (docker run -e / compose environment), see DEPLOY.md.

EXPOSE 8420

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
