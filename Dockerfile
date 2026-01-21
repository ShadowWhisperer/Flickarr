FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py .
COPY static ./static
COPY templates ./templates

# Create data directory and non-root user
RUN mkdir -p /app/data && \
    useradd -m -u 1000 flickarr && \
    chown -R flickarr:flickarr /app

# Switch to non-root user
USER flickarr

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:5000/', timeout=5)"

# Run the application
CMD ["python", "-u", "main.py"]
