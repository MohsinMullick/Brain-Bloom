# Use a lightweight Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements.txt
COPY requirements.txt .

# Install dependencies with CPU-only torch, using --no-cache-dir to reduce disk usage
RUN pip install --no-cache-dir -r requirements.txt -f https://download.pytorch.org/whl/cpu

# Copy the rest of the application code
COPY . .

# Command to run (Fly.io will override this with the [processes] from fly.toml)
CMD ["celery", "-A", "brain-bloom-django", "worker", "--loglevel=info"]