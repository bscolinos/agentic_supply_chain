FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# Copy application code
COPY api/ /app/api/
COPY schema/ /app/schema/
COPY simulator/ /app/simulator/
COPY .env* /app/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
