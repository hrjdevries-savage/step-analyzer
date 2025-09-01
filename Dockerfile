# Gebruik een lichte Python-image
FROM python:3.11-slim

# Zorg dat Python output direct gelogd wordt
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Werkdirectory binnen container
WORKDIR /app

# Kopieer requirements naar de container
COPY requirements.txt ./

# Installeer OCP apart, daarna de rest van requirements
RUN pip install --no-cache-dir "OCP==0.1.9" \
 && pip install --no-cache-dir -r requirements.txt \
 && python -c "import sys; print('Python:', sys.version); import OCP; import OCP.STEPControl as _; print('OCP import OK')"

# Kopieer de rest van de app-code
COPY . .

# Exposeer poort 8000 (standaard voor Uvicorn)
EXPOSE 8000

# Start de server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
