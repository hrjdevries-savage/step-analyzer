# Lichtgewicht Conda image
FROM mambaorg/micromamba:1.5.8

# Dit zorgt dat "base" geactiveerd is voor CMD
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# Installeer alle deps direct vanuit conda-forge (GEEN environment.yml)
RUN micromamba install -y -n base -c conda-forge \
    python=3.11 \
    fastapi=0.115.0 \
    uvicorn=0.30.6 \
    requests=2.32.3 \
    pythonocc-core=7.7.1 \
 && micromamba clean -a -y

# App files
WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER . .

# Render geeft PORT mee; fallback 8080
ENV PORT=8080
EXPOSE 8080

# Start in de (geactiveerde) conda base env
CMD ["/bin/bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
