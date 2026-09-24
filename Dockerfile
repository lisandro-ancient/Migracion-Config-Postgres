# Imagen del panel (Centro de control de migración) y de la CLI.
# Cliente de Firebird: libfbclient2 de Debian (se conecta por red a un Firebird Server;
# el modo embebido de macOS no aplica dentro del contenedor).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    CONFIG_MICROSIP_DATOS=/datos \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libfbclient2 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 migracion

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY src ./src
COPY dashboard ./dashboard
COPY pyproject.toml ./
# Manifiestos y snapshots van a la raíz de datos (/datos), que puede montarse como volumen
# para conservar runs/ y runs.db entre reinicios.
COPY --chown=migracion:migracion fuentes /datos/fuentes
COPY --chown=migracion:migracion fixtures /datos/fixtures

USER migracion
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8020/fragmento/dashboard', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8020"]
