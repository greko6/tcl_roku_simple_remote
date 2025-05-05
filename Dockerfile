# Use official Python 3.9 slim base image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY server.py .
COPY roku_control.html .
COPY manifest.json .
COPY service-worker.js .
COPY icons/ ./icons/

# Expose port 5050
EXPOSE 5050

# Command to run the application
CMD ["python", "server.py"]

