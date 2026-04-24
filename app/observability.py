"""Componentes de observabilidade e métricas da aplicação."""

from __future__ import annotations

import threading


class ObservabilityState:
    """Armazena contadores operacionais em memória de forma thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.webhook_total = 0
        self.messages_processed_total = 0
        self.messages_ignored_total = 0
        self.messages_duplicate_total = 0
        self.processing_errors_total = 0
        self.last_processing_seconds = 0.0

    def mark_webhook(self) -> None:
        with self._lock:
            self.webhook_total += 1

    def mark_processed(self) -> None:
        with self._lock:
            self.messages_processed_total += 1

    def mark_ignored(self) -> None:
        with self._lock:
            self.messages_ignored_total += 1

    def mark_duplicate(self) -> None:
        with self._lock:
            self.messages_duplicate_total += 1

    def mark_error(self) -> None:
        with self._lock:
            self.processing_errors_total += 1

    def set_last_processing_seconds(self, seconds: float) -> None:
        with self._lock:
            self.last_processing_seconds = seconds

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "webhook_total": float(self.webhook_total),
                "messages_processed_total": float(self.messages_processed_total),
                "messages_ignored_total": float(self.messages_ignored_total),
                "messages_duplicate_total": float(self.messages_duplicate_total),
                "processing_errors_total": float(self.processing_errors_total),
                "last_processing_seconds": self.last_processing_seconds,
            }


def build_prometheus_metrics(snapshot: dict[str, float], db_ready: bool, db_latency_ms: float) -> str:
    """Renderiza o payload de métricas no formato texto do Prometheus."""
    db_ready_value = 1 if db_ready else 0
    lines = [
        "# HELP chatbot_webhook_requests_total Total de webhooks recebidos.",
        "# TYPE chatbot_webhook_requests_total counter",
        f"chatbot_webhook_requests_total {int(snapshot['webhook_total'])}",
        "# HELP chatbot_messages_processed_total Total de mensagens processadas com resposta.",
        "# TYPE chatbot_messages_processed_total counter",
        f"chatbot_messages_processed_total {int(snapshot['messages_processed_total'])}",
        "# HELP chatbot_messages_ignored_total Total de mensagens ignoradas por payload inválido.",
        "# TYPE chatbot_messages_ignored_total counter",
        f"chatbot_messages_ignored_total {int(snapshot['messages_ignored_total'])}",
        "# HELP chatbot_messages_duplicate_total Total de mensagens descartadas por idempotência.",
        "# TYPE chatbot_messages_duplicate_total counter",
        f"chatbot_messages_duplicate_total {int(snapshot['messages_duplicate_total'])}",
        "# HELP chatbot_message_processing_errors_total Total de erros no processamento de mensagens.",
        "# TYPE chatbot_message_processing_errors_total counter",
        f"chatbot_message_processing_errors_total {int(snapshot['processing_errors_total'])}",
        "# HELP chatbot_webhook_last_processing_seconds Duração do último processamento de webhook.",
        "# TYPE chatbot_webhook_last_processing_seconds gauge",
        f"chatbot_webhook_last_processing_seconds {snapshot['last_processing_seconds']:.6f}",
        "# HELP chatbot_database_ready Estado do banco (1=up, 0=down).",
        "# TYPE chatbot_database_ready gauge",
        f"chatbot_database_ready {db_ready_value}",
        "# HELP chatbot_database_latency_ms Latência do check de banco em milissegundos.",
        "# TYPE chatbot_database_latency_ms gauge",
        f"chatbot_database_latency_ms {db_latency_ms}",
    ]
    return "\n".join(lines) + "\n"
