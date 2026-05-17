"""OpenTelemetry instrumentation. Active only when OTEL_EXPORTER_OTLP_ENDPOINT is set.

Configure via env:
  OTEL_EXPORTER_OTLP_ENDPOINT — OTLP collector URL (e.g. https://otel.grafana.com)
  OTEL_EXPORTER_OTLP_HEADERS  — auth headers, format "key=value,key2=value2"
  OTEL_SERVICE_NAME           — defaults to "cleanbrowser-manager"
  OTEL_RESOURCE_ATTRIBUTES    — extra attrs e.g. "environment=production,version=1.0"
"""
from __future__ import annotations
import logging, os

logger = logging.getLogger(__name__)

def is_configured() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))

def setup_tracing(app=None) -> None:
    """Initialize OTel tracer + auto-instrument FastAPI + psycopg2.
    Silent no-op if not configured."""
    if not is_configured():
        logger.info("OTel: OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping instrumentation")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "cleanbrowser-manager"),
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter()  # reads env automatically
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument FastAPI + psycopg2 + httpx
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)

        try:
            from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
            Psycopg2Instrumentor().instrument()
        except Exception:
            logger.warning("OTel psycopg2 instrumentation failed", exc_info=True)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except Exception:
            pass

        logger.info("OTel: tracing initialized for service=%s",
                    os.environ.get("OTEL_SERVICE_NAME", "cleanbrowser-manager"))
    except ImportError as e:
        logger.warning("OTel packages missing, skipping instrumentation: %s", e)
    except Exception:
        logger.exception("OTel setup failed — continuing without tracing")
