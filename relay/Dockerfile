FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir aiohttp

# Copy relay server
COPY datacore-msg-relay.py .

# Environment
ENV PORT=8080
ENV RELAY_SECRET=""

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/status')" || exit 1

CMD ["python", "datacore-msg-relay.py"]
