# Dockerfile per i nodi
FROM python:3.12-slim

# Installa dipendenze sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copia applicazione
WORKDIR /app
COPY ../node/ .

# Installa dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Esegui
CMD ["python", "node_server.py"]