"""Stage 1: ingest. Read -> detect source -> validate schema -> parse -> quarantine."""

from .detect import detect_source, read_table  # noqa: F401
