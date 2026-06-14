# Spec 19 — Despliegue en la nube

**Artefactos:** `Dockerfile`, `docker-compose.yml`, `deploy/k8s/`

## Propósito

Llevar cadvcs a producción en un proveedor cloud aprovechando que el estado está externalizado: la API y los workers son stateless, así que escalan horizontalmente, y la durabilidad recae en servicios gestionados.

## Comportamiento

La unidad de despliegue es una sola imagen Docker (`Dockerfile`) que sirve para los tres roles según el comando: API (`uvicorn`, por defecto), relay (`worker --mode relay`) y consumer (`worker --mode consume`). La imagen instala los extras `api,cache,events,s3`, de modo que un mismo contenedor puede hablar con PostgreSQL, Redis, Kafka y object storage según las variables de entorno que reciba; sin esas variables, cada integración degrada a no-op y el contenedor sigue funcionando.

El estado se delega a servicios gestionados: PostgreSQL (RDS / Cloud SQL) para la metadata, object storage S3-compatible (S3 / GCS / OCI / Azure Blob) para los blobs, y opcionalmente Redis (ElastiCache / Memorystore) para el cache de renders y Kafka (MSK / Confluent) para el transporte de eventos. La migración del esquema es automática e idempotente: API y workers crean las tablas al arrancar, sin paso de migración manual.

Topología (`deploy/k8s/`): la API corre con varias réplicas tras un Service e Ingress TLS, con HPA por CPU porque es lo que ve los picos de tráfico. El relay corre como una única réplica (publicar el outbox desde varias instancias sería trabajo redundante; el reenvío es inofensivo por idempotencia pero innecesario). El consumer escala horizontalmente: el consumer group de Kafka reparte las particiones entre réplicas, y su HPA sube réplicas bajo carga de indexado/conversión. El probe de liveness/readiness es `/health`, que queda fuera de la autenticación y reporta el estado de cada dependencia.

Sin Kafka, la topología se simplifica a un único `worker --mode poll` que drena el outbox directamente, eliminando relay y broker — válido para despliegues pequeños.

## Decisiones de diseño

Una sola imagen multi-rol en vez de tres imágenes: simplifica el build, el registro y el versionado, y como el código de los tres roles ya vive en el mismo paquete, separarlos no aporta. La identidad de workload (IRSA en EKS, Workload Identity en GKE) es la vía recomendada para el acceso a object storage, evitando claves estáticas en Secrets; los manifiestos dejan el hueco para credenciales explícitas como alternativa para clouds sin ese mecanismo.

Externalizar a servicios gestionados en vez de operar bases de datos en el clúster traslada el trabajo de durabilidad, backups y failover al proveedor, que es donde tiene sentido en producción; el `docker-compose.yml` mantiene la variante todo-en-uno (con Kafka en KRaft y Redis y PostgreSQL en contenedor) para desarrollo y evaluación.

## Limitaciones conocidas

El relay de una réplica no tiene HA automática: si su pod cae, hay una breve ventana sin publicación de eventos hasta que Kubernetes lo reprograma (el outbox conserva el trabajo, así que no se pierde nada, solo se retrasa). Leader-election para un relay activo-pasivo está en el ROADMAP. Los manifiestos no incluyen NetworkPolicies, PodDisruptionBudgets ni límites de cuota afinados; son una base correcta, no un endurecimiento completo para multi-tenant. El despliegue real en un proveedor concreto (Terraform de la VPC, el clúster gestionado, RDS/MSK/ElastiCache) queda fuera de estos manifiestos: aquí está el plano de aplicación, no el de infraestructura.
