"""Detection of unfilled placeholder values (PLACEHOLDER / FILL_IN / empty)."""
from typing import Any, Iterator

PLACEHOLDER_TOKENS = ("PLACEHOLDER", "FILL_IN")


def is_unset(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        v = value.strip()
        return v == "" or any(t in v.upper() for t in PLACEHOLDER_TOKENS)
    return False


def find_placeholders(obj: Any, path: str = "") -> Iterator[str]:
    """Yield the dotted path of every string value that still holds a placeholder."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from find_placeholders(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from find_placeholders(v, f"{path}[{i}]")
    elif isinstance(obj, str) and any(t in obj.upper() for t in PLACEHOLDER_TOKENS):
        yield path
