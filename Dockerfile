FROM python:3.12-slim-bookworm

WORKDIR /srv

COPY requirements.txt .
# RapidOCR depends on opencv-python, whose GUI bindings need libGL and libglib,
# which a slim image does not carry. The headless build is the same cv2 without
# them, so swap it in rather than installing an X stack we never use.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless

COPY app ./app
COPY static ./static
COPY samples ./samples
COPY run.py .

ENV PYTHONUNBUFFERED=1
# Honoured when the host does not inject its own PORT.
EXPOSE 8000
CMD ["python", "run.py"]
