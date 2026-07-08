"""
Struktūrizuoto (JSON) logging konfigūracija.

PROBLEMA, kurią sprendžia: iki šiol visur naudotas `print()` - žmogui
patogu skaityti terminale, bet mašinai (log agregavimo sistemai, grep/jq
analizei, CI dashboard'ui) sunku patikimai parsinti laisvo teksto eilutes.

SPRENDIMAS: kiekvienas log įrašas - viena JSON eilutė su fiksuota struktūra
(timestamp, level, logger, message + bet kokie papildomi struktūrizuoti
laukai per `extra={}`). Tai standartinė "structured logging" praktika.

Naudojimas:
    from logging_config import setup_logging, get_logger
    setup_logging()  # kviečiama VIENĄ kartą programos pradžioje (main.py)
    logger = get_logger(__name__)
    logger.info("Skelbimas rastas", extra={"source": "ExampleJobBoard1", "jobs_found": 5})

Formatas valdomas LOG_FORMAT aplinkos kintamuoju:
    LOG_FORMAT=json     -> viena JSON eilutė per įrašą (numatyta CI/produkcijai)
    LOG_FORMAT=console  -> žmogui skaitomas formatas (numatyta lokaliai, jei kintamasis nenustatytas)
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

# Standartiniai LogRecord atributai - naudojama atskirti "extra" laukus nuo
# vidinių logging modulio laukų, kai JsonFormatter juos serializuoja.
_STANDARD_LOG_RECORD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    """Formatuoja kiekvieną log įrašą kaip vieną JSON eilutę."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Bet kokie papildomi laukai, perduoti per extra={...}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key != "message":
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_format(json_format: bool = None) -> bool:
    if json_format is not None:
        return json_format
    return os.environ.get("LOG_FORMAT", "console").strip().lower() == "json"


def setup_logging(level: int = logging.INFO, json_format: bool = None) -> None:
    """
    Sukonfigūruoja root logger'į. Kviečiama VIENĄ kartą programos pradžioje.

    `json_format`: jei None (numatyta), sprendžiama pagal LOG_FORMAT env
    kintamąjį ("json" -> True, kitaip console/human-readable).
    """
    use_json = _resolve_format(json_format)

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    root = logging.getLogger()
    root.handlers = [handler]  # pašaliname senus handler'ius, kad nesidubliuotų
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
