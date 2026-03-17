import logging


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | trace=%(trace_id)s | %(message)s"


class DefaultTraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
            handler.addFilter(DefaultTraceIdFilter())
        return

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        handler.addFilter(DefaultTraceIdFilter())


class TraceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("trace_id", self.extra.get("trace_id", "-"))
        return msg, kwargs


def get_trace_logger(name: str, trace_id: str) -> TraceLoggerAdapter:
    return TraceLoggerAdapter(logging.getLogger(name), {"trace_id": trace_id})
