"""
RSends Backend — OpenTelemetry Setup.

Configures distributed tracing with:
  - OTLP gRPC exporter (when OTEL_ENDPOINT is set)
  - FastAPI auto-instrumentation (HTTP spans)
  - SQLAlchemy auto-instrumentation (DB query spans)

No-op if OTEL_ENDPOINT is not configured or if OTel packages are missing.
"""

import logging

logger = logging.getLogger(__name__)


def setup_telemetry(app, db_engine) -> bool:
    """Initialize OpenTelemetry tracing.

    Args:
        app: FastAPI application instance.
        db_engine: SQLAlchemy async engine (sync_engine used for instrumentation).

    Returns:
        True if tracing was initialized, False if skipped.
    """
    from app.config import get_settings
    settings = get_settings()

    if not settings.otel_endpoint:
        logger.debug("OTEL_ENDPOINT not set — tracing disabled")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError:
        logger.warning(
            "OpenTelemetry packages not installed — tracing disabled. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-sqlalchemy "
            "opentelemetry-exporter-otlp"
        )
        return False

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
    )
    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health.*,metrics",
    )

    # Auto-instrument SQLAlchemy
    SQLAlchemyInstrumentor().instrument(engine=db_engine.sync_engine)

    logger.info(
        "OpenTelemetry tracing enabled — exporting to %s",
        settings.otel_endpoint,
    )
    return True
