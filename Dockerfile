FROM python:3.11-slim
WORKDIR /app
# libgomp1 is required by xgboost (OpenMP runtime)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
# Use a single worker to stay within Railway free tier memory limits (512 MB)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --timeout 120 server:app"]
