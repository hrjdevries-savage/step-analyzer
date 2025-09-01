FROM python:3.11-slim

# Snellere/kleinere build + libs die vaak nodig zijn (OCP gebruikt native libs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# eerst alleen requirements kopiëren voor betere cache
COPY requirements.txt ./

RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 # Vroeg-valideren: als dit import-stapje faalt, is het meteen duidelijk in de build
 && python -c "import sys; print('Python:', sys.version); import OCP; import OCP.STEPControl as _; print('OCP import OK')"

# rest van de code
COPY . .

# (Render leest PORT env zelf in)
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
