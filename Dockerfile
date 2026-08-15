# Dockerfile para despliegue autónomo o en servidor/NAS de Fuente Knowledge Base
FROM python:3.11-slim

# Evitar escritura de bytecode de python y forzar buffering de logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar dependencias del sistema operativo (Poppler, Tesseract OCR, Git, C-compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    tesseract-ocr \
    tesseract-ocr-spa \
    poppler-utils \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar manifiesto de dependencias e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente del proyecto
COPY . .
RUN pip install --no-cache-dir -e .

# Definir volumen predeterminado para el Vault de Obsidian
VOLUME ["/vault"]

# Comando por defecto: worker headless continuo sobre el Vault montado en /vault
ENTRYPOINT ["fuente"]
CMD ["--headless", "--vault", "/vault"]
