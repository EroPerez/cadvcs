"""Transporte de eventos sobre Kafka (opcional).

El outbox de PostgreSQL/SQLite es la fuente de verdad transaccional (un
evento por blob a procesar, escrito en la misma transacción del commit).
Kafka es un **transporte opcional sobre ese outbox**, no un reemplazo: un
*relay* lee filas pending del outbox y las publica en un topic; los
*consumers* (indexado, conversión) reciben los eventos y procesan. El
estado sigue en el outbox, así que Kafka puede caerse y reiniciarse sin
perder trabajo — el relay reanuda desde las filas pending.

Degradación: sin `CADVCS_KAFKA_BROKERS`, no hay transporte Kafka y el
worker de polling (cadvcs.worker) sigue siendo el camino de proceso. Con
Kafka, el relay + consumers escalan horizontalmente (un consumer group
reparte particiones), que es la forma de producción de ARCHITECTURE.md.

La lógica del relay/consumer es agnóstica del cliente concreto: se prueba
con un transporte en memoria (`InMemoryBus`) y se ejecuta en producción
con `KafkaBus`. Misma lógica, distinto cable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TOPIC = "cadvcs.index"


class Bus:
    """Transporte abstracto publish/consume."""

    def publish(self, topic: str, key: str, value: dict) -> None:
        raise NotImplementedError

    def consume(self, topic: str, group: str, handler, max_messages=None):
        raise NotImplementedError

    def available(self) -> bool:
        return True


class InMemoryBus(Bus):
    """Transporte en memoria para tests: una cola por topic. Determinista
    y sin dependencias, ejercita exactamente la lógica de relay/consumer."""

    def __init__(self):
        self.queues: dict[str, list] = {}

    def publish(self, topic, key, value):
        self.queues.setdefault(topic, []).append((key, value))

    def consume(self, topic, group, handler, max_messages=None):
        q = self.queues.get(topic, [])
        n = 0
        while q and (max_messages is None or n < max_messages):
            key, value = q.pop(0)
            handler(key, value)
            n += 1
        return n

    def available(self):
        return True


class KafkaBus(Bus):  # pragma: no cover - requiere broker
    """Transporte Kafka real (kafka-python). Requiere CADVCS_KAFKA_BROKERS."""

    def __init__(self, brokers: str | None = None):
        self.brokers = brokers or os.environ.get("CADVCS_KAFKA_BROKERS")
        self._producer = None

    def available(self):
        if not self.brokers:
            return False
        try:
            from kafka import KafkaProducer  # noqa: F401
            return True
        except Exception:
            return False

    def _prod(self):
        if self._producer is None:
            from kafka import KafkaProducer
            self._producer = KafkaProducer(
                bootstrap_servers=self.brokers.split(","),
                key_serializer=lambda k: k.encode() if k else None,
                value_serializer=lambda v: json.dumps(v).encode(),
                acks="all", retries=3, enable_idempotence=True)
        return self._producer

    def publish(self, topic, key, value):
        p = self._prod()
        p.send(topic, key=key, value=value)
        p.flush()

    def consume(self, topic, group, handler, max_messages=None):
        from kafka import KafkaConsumer
        consumer = KafkaConsumer(
            topic, bootstrap_servers=self.brokers.split(","),
            group_id=group, enable_auto_commit=False,
            value_deserializer=lambda b: json.loads(b.decode()),
            key_deserializer=lambda b: b.decode() if b else None,
            auto_offset_reset="earliest", consumer_timeout_ms=2000)
        n = 0
        for msg in consumer:
            handler(msg.key, msg.value)
            consumer.commit()
            n += 1
            if max_messages is not None and n >= max_messages:
                break
        consumer.close()
        return n


def get_bus() -> Bus:
    """KafkaBus si hay brokers configurados y cliente disponible, si no None."""
    bus = KafkaBus()
    return bus if bus.available() else None


# --------------------------------------------------------------------------
# Relay: outbox → bus.  Publica las filas pending como eventos.
# --------------------------------------------------------------------------
def relay_once(repo, bus: Bus, topic: str = TOPIC, limit: int = 100) -> int:
    """Publica los eventos pending del outbox de un repo en el bus.

    No marca done aquí: el consumer es quien procesa y cierra el evento
    (vía repo.index_one). El relay solo transporta. Reenviar un evento ya
    procesado es inofensivo porque index_one es idempotente.
    """
    published = 0
    for ev in repo.index_pending(limit):
        bus.publish(topic, ev["blob_sha"], {
            "event_id": ev["id"], "blob_sha": ev["blob_sha"],
            "kind": ev.get("kind", "index"), "repo_key": repo.root.name})
        published += 1
    return published


# --------------------------------------------------------------------------
# Consumer: bus → repo.index_one.  Procesa eventos y cierra el outbox.
# --------------------------------------------------------------------------
def make_handler(repo_resolver):
    """Crea un handler que resuelve el repo por repo_key y procesa el evento.

    `repo_resolver(repo_key) -> Repo` permite a un consumer servir varios
    repos (cada evento lleva su repo_key).
    """
    def handler(key, value):
        repo = repo_resolver(value["repo_key"])
        if repo is None:
            return
        repo.index_one(value["event_id"], value["blob_sha"],
                       value.get("kind", "index"))
    return handler
