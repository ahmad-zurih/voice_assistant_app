# Use a smaller base image for efficiency
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies (including netcat)
RUN apt-get update && apt-get install -y netcat-openbsd && apt-get clean

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app into the container
COPY . /app

# Create directory for static files
RUN mkdir -p /app/staticfiles

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose the port Django runs on
EXPOSE 8000

# Copy and set permissions for the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Entrypoint script for running migrations & starting the server
ENTRYPOINT ["./entrypoint.sh"]
