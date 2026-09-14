FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INVENTORY_COOKIE_SECURE=true \
    INVENTORY_DEV_RETURN_OTP=false \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
EXPOSE 8000
CMD ["python", "-m", "inventory_management"]

