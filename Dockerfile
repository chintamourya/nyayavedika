FROM python:3.12-slim

# Tesseract OCR (Apache-2.0) with Indian language packs
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-tel tesseract-ocr-tam \
        tesseract-ocr-kan tesseract-ocr-mar tesseract-ocr-ben \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m nyayavedika && chown -R nyayavedika /app
USER nyayavedika
# Host, port and every other setting come from the mounted /app/.env (see docker-compose.yml)

CMD ["sh", "-c", "printf '%s' \"$DOTENV_B64\" | base64 -d > /app/.env && exec python server.py"]
