# Spec 17 — Transporte de eventos sobre Kafka

**Módulos:** `cadvcs/bus.py` (`Bus`, `InMemoryBus`, `KafkaBus`, `relay_once`, `make_handler`), modos `relay`/`consume` en `cadvcs/worker.py`

## Propósito

Escalar el procesamiento de eventos horizontalmente. El worker de polling (spec 12) drena el outbox en proceso; en producción se quiere un transporte que reparta el trabajo entre varios consumidores con reanudación ante fallos. Eso es Kafka, como pide ARCHITECTURE.md.

## Comportamiento

El outbox de la base de datos sigue siendo la **fuente de verdad transaccional**: un evento por blob a procesar, escrito en la misma transacción del commit (spec 12). Kafka es un **transporte sobre ese outbox**, no un reemplazo. Un *relay* lee las filas `pending` del outbox y las publica en el topic `cadvcs.index`; los *consumers* (un consumer group que reparte particiones) reciben los eventos y los procesan llamando a `repo.index_one`, que es lo mismo que hace el worker de polling. El relay no marca los eventos como hechos: es el consumer quien procesa y cierra el outbox. Por eso Kafka puede caerse y reiniciarse sin perder trabajo —el relay reanuda desde las filas `pending`— y reenviar un evento ya procesado es inofensivo, porque `index_one` es idempotente.

El worker gana dos modos sobre el `poll` por defecto: `--mode relay` (outbox → Kafka) y `--mode consume` (Kafka → `index_one`). Escalar es añadir réplicas del consumer: el consumer group de Kafka les reparte las particiones.

Degradación: sin `CADVCS_KAFKA_BROKERS`, no hay bus Kafka y el worker de polling sigue siendo el camino de proceso, idéntico a antes de esta spec.

## Decisiones de diseño

La lógica de relay y consumer es **agnóstica del cliente concreto**: `Bus` es una interfaz publish/consume con dos implementaciones, `KafkaBus` (producción) e `InMemoryBus` (tests). Eso permite verificar exactamente la lógica de transporte —relay publica las filas pending, el consumer procesa y cierra el outbox, la idempotencia ante reenvío— de forma determinista y sin un broker, ejercitando el mismo código que corre en producción solo con distinto cable.

Mantener el outbox como fuente de verdad (en vez de publicar a Kafka directamente desde el commit) es lo que da atomicidad entre metadata y evento sin un commit distribuido: la fila del outbox y el commit entran en la misma transacción de base de datos; el relay es un proceso aparte que no puede perder eventos confirmados.

## Limitaciones conocidas

La integración con un broker Kafka real va en `docker-compose.yml` (servicios `kafka`, `relay`, `worker --mode consume`) y requiere un broker en CI con servicios para una prueba de extremo a extremo; el test cubre la lógica con `InMemoryBus`, no la entrega real de Kafka. El relay es at-least-once: un consumer podría procesar un evento dos veces (tolerado por idempotencia) pero no menos de una. No hay todavía partición por `repo_key` para garantizar orden por repo —los eventos son idempotentes e independientes, así que el orden no afecta a la correctitud, pero un esquema de claves por repo mejoraría la localidad.
