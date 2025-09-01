# Gebruik micromamba als lichte conda image
FROM mambaorg/micromamba:1.5.8

# Zet werkdirectory
WORKDIR /app

# Kopieer de hele app
COPY --chown=mambauser:mambauser . .

# Maak een environment.yml met alle dependencies
# (Als je environment.yml al hebt, prima. Anders maken we deze inhoud)
# name: base
# dependencies:
#   - python=3.11
#   - pip
#   - pip:
#       - fastapi==0.115.0
#       - uvicorn==0.30.6
#       - requests==2.32.3
#       - pythonocc-core==7.7.2

# Installeer environment met micromamba
RUN micromamba install -n base -y -f environment.yml && \
    micromamba clean --all --yes

# Check dat uvicorn en pythonocc-core goed werken
RUN micromamba run -n base uvicorn --version

# Start app via micromamba zodat de conda environment actief is
CMD ["micromamba", "run", "-n", "base", "bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
