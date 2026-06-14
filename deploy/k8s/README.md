# Despliegue en Kubernetes

Manifiestos para desplegar cadvcs en un clúster gestionado (EKS, GKE, AKS).
Aplican el patrón de servicios externalizados: la API y los workers son
stateless; el estado vive en servicios gestionados.

## Qué provisionar fuera del clúster (gestionado, recomendado)

- **PostgreSQL** (RDS / Cloud SQL / Azure Database): metadata. Apuntar
  `PGHOST` en el ConfigMap y `POSTGRES_PASSWORD` en el Secret.
- **Object storage** (S3 / GCS / OCI / Azure Blob con compat S3): blobs.
  `CADVCS_BLOB_URL=s3://bucket/prefijo`. En EKS/GKE, preferir identidad de
  workload (IRSA / Workload Identity) y omitir las claves del Secret.
- **Redis** (ElastiCache / Memorystore): cache de renders. Opcional.
- **Kafka** (MSK / Confluent Cloud): transporte de eventos. Opcional; sin
  él, usar un único `worker --mode poll` en vez de relay+consumer.

Redis y Kafka también pueden correr dentro del clúster (operadores como
Strimzi para Kafka); el `docker-compose.yml` muestra esa variante para
desarrollo.

## Aplicar

```bash
# 1. Crear el Secret de verdad (no usar la plantilla en producción)
kubectl create namespace cadvcs
kubectl -n cadvcs create secret generic cadvcs-secrets \
  --from-literal=POSTGRES_PASSWORD=... \
  --from-literal=AWS_ACCESS_KEY_ID=... \
  --from-literal=AWS_SECRET_ACCESS_KEY=... \
  --from-literal=AWS_DEFAULT_REGION=eu-west-1

# 2. Ajustar 01-config.yaml (hosts, bucket, issuer OIDC) y aplicar el resto
kubectl apply -f 00-namespace.yaml -f 01-config.yaml \
  -f 03-api.yaml -f 04-workers.yaml -f 05-ingress.yaml
```

La migración del esquema es automática: la API y los workers crean las
tablas al arrancar (idempotente). No hay paso de migración manual.

## Componentes

| Manifiesto | Qué despliega | Escala |
|------------|---------------|--------|
| `03-api.yaml` | API REST + Web UI (3 réplicas, HPA a 10) | horizontal por CPU |
| `04-workers.yaml` | relay (1) + worker/consumer (2, HPA a 8) | consumer group de Kafka |
| `05-ingress.yaml` | Ingress TLS público | — |

## Verificación tras desplegar

```bash
kubectl -n cadvcs get pods
kubectl -n cadvcs exec deploy/cadvcs-api -- \
  python -c "import urllib.request,json; \
  print(json.load(urllib.request.urlopen('http://localhost:8000/health')))"
```

El `/health` reporta el estado de cada pieza (`backend`, `render_cache`,
`event_bus`, `dwg_converter`), útil para confirmar que la API ve
PostgreSQL, Redis y Kafka.
