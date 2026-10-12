FROM python:3.12-slim
ARG BUILD_VERSION=0.3.1
ARG BUILD_ARCH=amd64
LABEL io.hass.name="Predictratron" io.hass.description="Local time-series prediction for Home Assistant" \
    io.hass.version="${BUILD_VERSION}" io.hass.type="app" io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/AndreasFridh/Predictratron"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home predictor \
    && mkdir /data && chown predictor:predictor /data
COPY --chown=predictor:predictor app ./app
# The launcher fixes the Supervisor data volume ownership and drops to uid 10001.
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "-m", "app.launch"]
