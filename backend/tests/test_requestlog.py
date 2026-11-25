import logging
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import requestlog


@pytest.fixture
def client():
    app = FastAPI()
    requestlog.install(app)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/slow")
    async def slow():
        time.sleep(0.05)
        return {"ok": True}

    @app.get("/refuse")
    async def refuse():
        raise HTTPException(status_code=409, detail={"code": "google_reauth_required", "message": "Google access was revoked."})

    @app.get("/db-down")
    async def db_down():
        raise HTTPException(status_code=502, detail="Database error: connection refused for key SECRETVALUE")

    @app.get("/crash")
    async def crash():
        raise RuntimeError("boom with password hunter2")

    @app.get("/typed/{n}")
    async def typed(n: int):
        return {"n": n}

    return TestClient(app, raise_server_exceptions=False)


def lines(caplog):
    return [r for r in caplog.records if r.name == "quickindex.request"]


def test_every_response_carries_a_request_id_and_good_requests_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO)
    r = client.get("/ok")
    assert r.status_code == 200 and len(r.headers["X-Request-ID"]) == 12
    assert lines(caplog) == []  # uvicorn's access log already covers successes: no duplicate line


def test_a_sensible_incoming_id_is_kept_and_a_hostile_one_is_replaced(client):
    assert client.get("/ok", headers={"X-Request-ID": "abc-123_DEF"}).headers["X-Request-ID"] == "abc-123_DEF"
    for bad in ("short", "has space in it", "x" * 200, "line\nbreak123", "<script>alert(1)</script>"):
        got = client.get("/ok", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
        assert got != bad and len(got) == 12


def test_a_refusal_is_logged_as_a_warning_with_its_code_and_the_client_still_gets_its_answer(client, caplog):
    caplog.set_level(logging.INFO)
    r = client.get("/refuse")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_reauth_required"  # response unchanged
    (rec,) = lines(caplog)
    msg = rec.getMessage()
    assert rec.levelno == logging.WARNING
    assert f"request_id={r.headers['X-Request-ID']}" in msg and "GET /refuse -> 409" in msg
    assert "google_reauth_required: Google access was revoked." in msg and "ms" in msg


def test_a_server_side_failure_is_logged_as_an_error_with_the_reason(client, caplog):
    caplog.set_level(logging.INFO)
    assert client.get("/db-down").status_code == 502
    (rec,) = lines(caplog)
    assert rec.levelno == logging.ERROR and "-> 502" in rec.getMessage() and "Database error" in rec.getMessage()


def test_a_crash_logs_the_traceback_but_tells_the_browser_nothing_but_the_id(client, caplog):
    caplog.set_level(logging.INFO)
    r = client.get("/crash")
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Something went wrong on our side." and body["request_id"] == r.headers["X-Request-ID"]
    assert "hunter2" not in r.text and "RuntimeError" not in r.text and "Traceback" not in r.text
    (rec,) = lines(caplog)
    assert rec.levelno == logging.ERROR and rec.exc_info and "unhandled error" in rec.getMessage()
    assert rec.exc_info[0] is RuntimeError  # the full traceback reaches the terminal


def test_the_query_string_is_never_logged(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/refuse?code=4/0AfJohXn-OAUTHCODE&state=SEALEDSTATE&access_token=TOKEN123")
    text = " ".join(r.getMessage() for r in lines(caplog))
    assert "/refuse" in text
    for secret in ("OAUTHCODE", "SEALEDSTATE", "TOKEN123", "?"):
        assert secret not in text


def test_validation_errors_are_logged_and_a_slow_request_is_flagged(client, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    assert client.get("/typed/abc").status_code == 422
    assert "-> 422" in lines(caplog)[0].getMessage() and lines(caplog)[0].levelno == logging.WARNING
    caplog.clear()
    monkeypatch.setattr(requestlog, "SLOW_SECONDS", 0.01)
    assert client.get("/slow").status_code == 200
    (rec,) = lines(caplog)
    assert rec.levelno == logging.WARNING and "(slow)" in rec.getMessage()


def test_detail_text_is_one_short_redacted_line():
    text = requestlog._detail_text("first line\nsecond ?code=ABC123&x=1 " + "z" * 1000)
    assert "\n" not in text and "ABC123" not in text and len(text) <= 300


def test_the_real_app_has_it_installed_and_exposes_the_id_to_the_browser():
    from app.main import app

    assert any(m.cls is requestlog.RequestLogMiddleware for m in app.user_middleware)
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert "X-Request-ID" in cors.kwargs["expose_headers"]
    names = [m.cls.__name__ for m in app.user_middleware]
    assert names.index("CORSMiddleware") < names.index("RequestLogMiddleware")  # CORS is outermost
