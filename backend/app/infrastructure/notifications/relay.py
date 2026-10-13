"""Stream names shared by optional inspection tools; Java owns all consumers."""


def _decode_text(value: object) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _field(mapping: dict[object, object], name: str, default: object = None) -> object:
    return mapping.get(name, mapping.get(name.encode(), default))


class RedisNotificationRelay:
    STREAM = "lab:v2:notification:events"
    DEAD_LETTER_STREAM = "lab:v2:notification:dead-letter"
    DEAD_LETTER_REPLAYED = "lab:v2:notification:dead-letter:replayed"
