FROM mambaorg/micromamba:1.5.8

# Snellere, kleinere env-install
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && \
    micromamba clean -a -y

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# Render geeft PORT mee; fallback voor lokaal
ENV PORT=10000
EXPOSE 10000

# Start de API
CMD ["bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
