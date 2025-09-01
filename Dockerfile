FROM python:3.11-slim

# Basis libs die OCP/uvicorn nodig heeft
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

# Upgrade pip -> install ALLES uit requirements -> valideer dat OCP te importeren is
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && python -c "import sys; print('Python:', sys.version); import OCP, OCP.STEPControl as _; print('OCP import OK')"

# Rest van de code
COPY . .

# Render stelt PORT in
ENV PORT=8000
EXPOSE 8000

# Start de app
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
