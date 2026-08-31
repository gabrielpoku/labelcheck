FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY samples ./samples
COPY run.py .

# Warm the OCR models at startup, not on the first request.
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "run.py"]
