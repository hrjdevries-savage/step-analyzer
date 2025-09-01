# Lichtgewicht Python + system libs die OCC nodig heeft
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Basislibs voor OpenCascade rendering/box berekening (zonder X-server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglu1-mesa \
    libxrender1 \
    libxext6 \
    libxi6 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Eerst requirements voor betere caching
COPY requirements.txt ./

# pip 23.x is wat toleranter; 24/25 triggert de OCP-marker bug die we nu vermijden.
RUN python -m pip install --upgrade "pip<24" \
 && pip --version \
 && pip install --no-cache-dir -r requirements.txt

# Dan je code
COPY . .

# Render levert PORT; fallback naar 10000
ENV PORT=10000

# Uvicorn starten
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"]
