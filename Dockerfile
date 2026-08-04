FROM python:3.13-slim

WORKDIR /app

# System deps needed by psycopg2-binary and reportlab at build time
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
EXPOSE 8000

# Default command runs the Streamlit dashboard.
# Override with `docker run <image> python -m uvicorn api:app --host 0.0.0.0 --port 8000`
# to run the API instead (see docker-compose.yml, which runs both as separate services).
CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
