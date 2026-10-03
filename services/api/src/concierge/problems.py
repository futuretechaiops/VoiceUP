"""RFC 7807 problem responses with a stable request id (spec section 9)."""

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_JSON = "application/problem+json"
log = logging.getLogger("concierge.problems")


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def problem(
    request: Request,
    status: int,
    title: str,
    code: str,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "type": f"https://docs.voiceup.example/problems/{code.lower()}",
        "title": title,
        "status": status,
        "code": code,
        "request_id": request_id_of(request),
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
        response = problem(request, exc.status_code, str(exc.detail), f"HTTP_{exc.status_code}")
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return problem(request, 422, "Request validation failed", "VALIDATION_ERROR", errors)

    @app.exception_handler(Exception)
    async def unhandled_problem(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": request_id_of(request)})
        return problem(request, 500, "Internal server error", "INTERNAL_ERROR")
