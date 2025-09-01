# Gebruik Micromamba (Conda) zodat pythonocc-core vanaf conda-forge werkt
FROM mambaorg/micromamba:1.5.8

# Installeer de environment uit environment.yml
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean -a -y

# App-bestanden
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# Render levert PORT mee; fallback 8080
ENV PORT=8080
EXPOSE 8080

# Start de app vanuit de conda (base) environment
CMD ["/bin/bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
