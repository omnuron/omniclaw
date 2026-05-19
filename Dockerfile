FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

# ─── Runtime stage ────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /app/ /app/

EXPOSE 8080

ENV OMNICLAW_REDIS_URL=redis://redis:6379/0

CMD ["uvicorn", "omniclaw.agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
