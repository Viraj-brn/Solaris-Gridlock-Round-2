FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies if required (e.g., for ML packages like LightGBM, CatBoost)
RUN apt-get update && apt-get install -y \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Command to run the FastAPI application
CMD ["uvicorn", "src.server.fastapi_server:app", "--host", "0.0.0.0", "--port", "8000"]
