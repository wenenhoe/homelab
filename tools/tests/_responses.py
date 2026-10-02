"""A real requests.Response for tests whose code under test reads one.

A test sets the status and the body; json(), text and raise_for_status()
are the library's own, so a test cannot read a field the real response
lacks or see a call succeed that the real one would reject.
"""

from __future__ import annotations

import json as _json
from http import HTTPStatus

import requests


def _reason(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""


def response(status_code: int = 200, json_body: object | None = None, text: str | None = None) -> requests.Response:
    """`json_body` is served as JSON; `text` as a plain body. Give one, or neither for an empty body."""
    if json_body is not None and text is not None:
        raise ValueError("give json_body or text, not both")
    resp = requests.Response()
    resp.status_code = status_code
    resp.reason = _reason(status_code)
    resp.url = "https://example.invalid/"
    resp.encoding = "utf-8"
    resp._content = (_json.dumps(json_body) if json_body is not None else (text or "")).encode()
    return resp
