# ---- Basis image met micromamba ----
FROM mambaorg/micromamba:1.5.8 AS base

# ---- Maak werkdirectory en kopieer files ----
WORKDIR /app
COPY --chown=mambauser:mambauser environment.yml /app/environment.yml
COPY --chown=mambauser:mambauser . /app

# ---- Installeer alles via micromamba ----
RUN micromamba install -y -n base -f /app/environment.yml && \
    micromamba clean --all --yes

# ---- Entrypoint: zorg dat alles altijd in de juiste env draait ----
COPY --chown=mambauser:mambauser <<'ENTRYPOINT' /usr/local/bin/entrypoint.sh
#!/usr/bin/env bash
set -e
exec micromamba run -n base "$@"
ENTRYPOINT
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# ---- Start Uvicorn server ----
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
