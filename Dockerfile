# Micromamba (Conda) image — lichtgewicht en ideaal voor conda-forge packages
FROM mambaorg/micromamba:1.5.8

# Maak de env vanuit environment.yml
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean -a -y

# App files
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# Render geeft PORT mee; fallback op 8080
ENV PORT=8080
EXPOSE 8080

# Start via de conda (base) omgeving
CMD ["/bin/bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
