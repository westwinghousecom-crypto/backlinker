"""Terminal logging for the API: one line per failed or slow request, with an id the browser console shows too.

Successful requests are already logged by uvicorn's access log, so this only adds what it lacks: the request id, how long
the request took, the error code or message the API returned, and a full traceback for crashes. It never logs the query
string, headers, cookies or request bodies (those can hold tokens, OAuth codes or customers' URLs).
"""
import logging
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.logfilter import redact

log = logging.getLogger("quickindex.request")

HEADER = "X-Request-ID"
SLOW_SECONDS = 2.0
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _request_id(request: Request) -> str:
    incoming = request.headers.get(HEADER, "")
    return incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex[:12]


def _detail_text(detail: object) -> str:
    """A short, single-line description of an HTTPException detail (string, or {code, message})."""
    if isinstance(detail, dict):
        code, message = detail.get("code"), detail.get("message")
        detail = f"{code}: {message}" if code and message else (code or message or "")
    return redact(" ".join(str(detail).split()))[:300]


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = _request_id(request)
        request.state.request_id = rid
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = (time.perf_counter() - started) * 1000
            log.exception("request_id=%s %s %s -> 500 in %.0fms (unhandled error)", rid, request.method, request.url.path, ms)
            # Nothing about the failure is sent to the browser except the id to quote when asking for help.
            response = JSONResponse({"detail": "Something went wrong on our side.", "request_id": rid}, status_code=500)
            response.headers[HEADER] = rid
            return response

        ms = (time.perf_counter() - started) * 1000
        response.headers[HEADER] = rid
        detail = getattr(request.state, "error_detail", "")
        suffix = f" [{detail}]" if detail else ""
        line = "request_id=%s %s %s -> %s in %.0fms%s"
        args = (rid, request.method, request.url.path, response.status_code, ms, suffix)
        if response.status_code >= 500:
            log.error(line, *args)
        elif response.status_code >= 400:
            log.warning(line, *args)
        elif ms >= SLOW_SECONDS * 1000:
            log.warning(line + " (slow)", *args)
        return response


async def _logged_http_exception(request: Request, exc: HTTPException) -> Response:
    """Remember why the API refused, so the one log line (written above) can say it."""
    request.state.error_detail = _detail_text(exc.detail)
    return await http_exception_handler(request, exc)


def install(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _logged_http_exception)
    app.add_middleware(RequestLogMiddleware)
