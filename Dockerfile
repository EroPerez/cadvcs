FROM python:3.12-slim

# Capa de dependencias cacheable
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cadvcs ./cadvcs
RUN pip install --no-cache-dir ".[api,cache,events,s3]" "psycopg[binary]>=3.1"

# Usuario no privilegiado y directorio de datos
RUN useradd -r -m cadvcs && mkdir -p /data && chown cadvcs /data
USER cadvcs
ENV CADVCS_DATA=/data
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "cadvcs.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
