from app.observability import ObservabilityState, build_prometheus_metrics


def test_observability_tracks_response_sources_and_error_types():
    state = ObservabilityState()
    state.mark_response_source("menu")
    state.mark_response_source("menu")
    state.mark_response_source("base de dados")
    state.mark_error()
    state.mark_error_type("send_failed")

    metrics = build_prometheus_metrics(
        state.snapshot(),
        db_ready=True,
        db_latency_ms=1.5,
    )

    assert 'chatbot_responses_by_source_total{source="menu"} 2' in metrics
    assert 'chatbot_responses_by_source_total{source="base_de_dados"} 1' in metrics
    assert 'chatbot_message_processing_errors_by_type_total{type="send_failed"} 1' in metrics
    assert "chatbot_message_processing_errors_total 1" in metrics
