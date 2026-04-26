"""Componentes de observabilidade e métricas da aplicação."""

from __future__ import annotations

import threading


class ObservabilityState:
    """Armazena contadores operacionais em memória de forma thread-safe."""

    duration_buckets: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.webhook_total = 0
        self.messages_processed_total = 0
        self.messages_recorded_total = 0
        self.messages_ignored_total = 0
        self.messages_duplicate_total = 0
        self.processing_errors_total = 0
        self.signature_failures_total = 0
        self.response_source_totals: dict[str, int] = {}
        self.processing_error_totals_by_type: dict[str, int] = {}
        self.last_processing_seconds = 0.0
        self.webhook_processing_duration_count = 0
        self.webhook_processing_duration_sum = 0.0
        self.webhook_processing_duration_buckets = {
            bucket: 0 for bucket in self.duration_buckets
        }

    def mark_webhook(self) -> None:
        with self._lock:
            self.webhook_total += 1

    def mark_processed(self) -> None:
        with self._lock:
            self.messages_processed_total += 1

    def mark_recorded(self) -> None:
        with self._lock:
            self.messages_recorded_total += 1

    def mark_ignored(self) -> None:
        with self._lock:
            self.messages_ignored_total += 1

    def mark_duplicate(self) -> None:
        with self._lock:
            self.messages_duplicate_total += 1

    def mark_error(self) -> None:
        with self._lock:
            self.processing_errors_total += 1

    def mark_error_type(self, error_type: str) -> None:
        normalized_type = _normalize_label_value(error_type)
        with self._lock:
            self.processing_error_totals_by_type[normalized_type] = (
                self.processing_error_totals_by_type.get(normalized_type, 0) + 1
            )

    def mark_response_source(self, source: str) -> None:
        normalized_source = _normalize_label_value(source)
        with self._lock:
            self.response_source_totals[normalized_source] = (
                self.response_source_totals.get(normalized_source, 0) + 1
            )

    def mark_signature_failure(self) -> None:
        with self._lock:
            self.signature_failures_total += 1

    def set_last_processing_seconds(self, seconds: float) -> None:
        with self._lock:
            self.last_processing_seconds = seconds
            self.webhook_processing_duration_count += 1
            self.webhook_processing_duration_sum += seconds
            for bucket in self.duration_buckets:
                if seconds <= bucket:
                    self.webhook_processing_duration_buckets[bucket] += 1

    def snapshot(self) -> dict[str, float | dict[float, int]]:
        with self._lock:
            return {
                "webhook_total": float(self.webhook_total),
                "messages_processed_total": float(self.messages_processed_total),
                "messages_recorded_total": float(self.messages_recorded_total),
                "messages_ignored_total": float(self.messages_ignored_total),
                "messages_duplicate_total": float(self.messages_duplicate_total),
                "processing_errors_total": float(self.processing_errors_total),
                "signature_failures_total": float(self.signature_failures_total),
                "response_source_totals": dict(self.response_source_totals),
                "processing_error_totals_by_type": dict(self.processing_error_totals_by_type),
                "last_processing_seconds": self.last_processing_seconds,
                "webhook_processing_duration_count": float(self.webhook_processing_duration_count),
                "webhook_processing_duration_sum": float(self.webhook_processing_duration_sum),
                "webhook_processing_duration_buckets": dict(self.webhook_processing_duration_buckets),
            }


def _normalize_label_value(value: str) -> str:
    normalized = (value or "unknown").strip().lower()
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in normalized) or "unknown"


def _labeled_counter_lines(
    metric_name: str,
    label_name: str,
    values: dict[str, int] | dict[str, float],
) -> list[str]:
    return [
        f'{metric_name}{{{label_name}="{label_value}"}} {int(count)}'
        for label_value, count in sorted(values.items())
    ]


def build_prometheus_metrics(
    snapshot: dict[str, float | dict[float, int]],
    db_ready: bool,
    db_latency_ms: float,
) -> str:
    """Renderiza o payload de métricas no formato texto do Prometheus."""
    db_ready_value = 1 if db_ready else 0
    duration_buckets = snapshot.get("webhook_processing_duration_buckets", {})
    lines = [
        "# HELP chatbot_webhook_requests_total Total de webhooks recebidos.",
        "# TYPE chatbot_webhook_requests_total counter",
        f"chatbot_webhook_requests_total {int(snapshot['webhook_total'])}",
        "# HELP chatbot_messages_processed_total Total de mensagens processadas com resposta.",
        "# TYPE chatbot_messages_processed_total counter",
        f"chatbot_messages_processed_total {int(snapshot['messages_processed_total'])}",
        "# HELP chatbot_messages_recorded_total Total de mensagens registradas sem resposta automática.",
        "# TYPE chatbot_messages_recorded_total counter",
        f"chatbot_messages_recorded_total {int(snapshot['messages_recorded_total'])}",
        "# HELP chatbot_messages_ignored_total Total de mensagens ignoradas por payload inválido.",
        "# TYPE chatbot_messages_ignored_total counter",
        f"chatbot_messages_ignored_total {int(snapshot['messages_ignored_total'])}",
        "# HELP chatbot_messages_duplicate_total Total de mensagens descartadas por idempotência.",
        "# TYPE chatbot_messages_duplicate_total counter",
        f"chatbot_messages_duplicate_total {int(snapshot['messages_duplicate_total'])}",
        "# HELP chatbot_message_processing_errors_total Total de erros no processamento de mensagens.",
        "# TYPE chatbot_message_processing_errors_total counter",
        f"chatbot_message_processing_errors_total {int(snapshot['processing_errors_total'])}",
        "# HELP chatbot_message_processing_errors_by_type_total Total de erros no processamento por tipo.",
        "# TYPE chatbot_message_processing_errors_by_type_total counter",
        *_labeled_counter_lines(
            "chatbot_message_processing_errors_by_type_total",
            "type",
            snapshot.get("processing_error_totals_by_type", {}),
        ),
        "# HELP chatbot_responses_by_source_total Total de respostas enviadas por origem.",
        "# TYPE chatbot_responses_by_source_total counter",
        *_labeled_counter_lines(
            "chatbot_responses_by_source_total",
            "source",
            snapshot.get("response_source_totals", {}),
        ),
        "# HELP chatbot_webhook_signature_failures_total Total de falhas de validação da assinatura do webhook.",
        "# TYPE chatbot_webhook_signature_failures_total counter",
        f"chatbot_webhook_signature_failures_total {int(snapshot.get('signature_failures_total', 0))}",
        "# HELP chatbot_webhook_last_processing_seconds Duração do último processamento de webhook.",
        "# TYPE chatbot_webhook_last_processing_seconds gauge",
        f"chatbot_webhook_last_processing_seconds {snapshot['last_processing_seconds']:.6f}",
        "# HELP chatbot_webhook_processing_duration_seconds Duração do processamento do webhook.",
        "# TYPE chatbot_webhook_processing_duration_seconds histogram",
    ]

    cumulative = 0
    for bucket in ObservabilityState.duration_buckets:
        cumulative = int(duration_buckets.get(bucket, cumulative))
        lines.append(
            f'chatbot_webhook_processing_duration_seconds_bucket{{le="{bucket}"}} {cumulative}'
        )
    total_count = int(snapshot.get("webhook_processing_duration_count", 0))
    lines.append(
        'chatbot_webhook_processing_duration_seconds_bucket{le="+Inf"} '
        f"{total_count}"
    )
    lines.append(
        f"chatbot_webhook_processing_duration_seconds_sum {snapshot.get('webhook_processing_duration_sum', 0.0):.6f}"
    )
    lines.append(
        f"chatbot_webhook_processing_duration_seconds_count {total_count}"
    )
    lines += [
        "# HELP chatbot_database_ready Estado do banco (1=up, 0=down).",
        "# TYPE chatbot_database_ready gauge",
        f"chatbot_database_ready {db_ready_value}",
        "# HELP chatbot_database_latency_ms Latência do check de banco em milissegundos.",
        "# TYPE chatbot_database_latency_ms gauge",
        f"chatbot_database_latency_ms {db_latency_ms}",
    ]
    return "\n".join(lines) + "\n"
