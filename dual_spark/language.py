"""Small English/Russian selector for installer prompts and status."""

import os
import re


def resolve_language(choice="auto", environ=None):
    if choice in ("en", "ru"):
        return choice
    if choice != "auto":
        raise ValueError(f"Unsupported language: {choice}")
    values = os.environ if environ is None else environ
    override = values.get("CONNECT_DUAL_SPARK_LANG", "").lower()
    if override in ("en", "ru"):
        return override
    locale = values.get("LC_ALL") or values.get("LC_MESSAGES") or values.get("LANG", "")
    return "ru" if re.match(r"^ru(?:$|[_\-.@])", locale.lower()) else "en"


_current_language = resolve_language()


def set_language(language):
    global _current_language
    if language not in ("en", "ru"):
        raise ValueError(f"Unsupported language: {language}")
    _current_language = language


def current_language():
    return _current_language


def msg(english, russian):
    return russian if _current_language == "ru" else english
