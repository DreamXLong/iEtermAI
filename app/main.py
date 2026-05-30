from __future__ import annotations

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from .automation_windows import AutomationError, build_automation
from .config import settings
from .executor import IETermService
from .mobile import render_mobile_console
from .models import (
    FareQueryResponse,
    FareCalculationResponse,
    FlightQuery,
    HealthResponse,
    InternationalFareQuery,
    LoginAliasOptions,
    QueryResponse,
    RawCommandRequest,
    RawCommandResponse,
    SelectLoginAliasRequest,
    SessionSnapshot,
)
from .session import SessionManager

app = FastAPI(title=settings.service_name)

session_manager = SessionManager()
automation = build_automation(settings)
service = IETermService(
    automation=automation,
    session_manager=session_manager,
    settings=settings,
)


def require_mobile_token(
    x_ieterm_token: Optional[str] = Header(default=None, alias="X-IETERM-Token"),
    token: Optional[str] = Query(default=None),
) -> None:
    expected_token = settings.mobile_access_token
    if not expected_token:
        return
    supplied_token = x_ieterm_token or token
    if supplied_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid or missing access token.")


@app.get("/mobile", response_class=HTMLResponse)
def mobile_console() -> HTMLResponse:
    return HTMLResponse(render_mobile_console())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(service=settings.service_name, status="ok")


@app.get("/session/status", response_model=SessionSnapshot, dependencies=[Depends(require_mobile_token)])
def session_status() -> SessionSnapshot:
    try:
        return service.session_status()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/ensure-ready", response_model=SessionSnapshot, dependencies=[Depends(require_mobile_token)])
def ensure_ready() -> SessionSnapshot:
    try:
        return service.ensure_ready()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/login", response_model=SessionSnapshot, dependencies=[Depends(require_mobile_token)])
def login() -> SessionSnapshot:
    try:
        return service.login()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/session/login-aliases", response_model=LoginAliasOptions, dependencies=[Depends(require_mobile_token)])
def login_aliases() -> LoginAliasOptions:
    try:
        return service.list_login_aliases()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/login-alias", response_model=LoginAliasOptions, dependencies=[Depends(require_mobile_token)])
def select_login_alias(payload: SelectLoginAliasRequest) -> LoginAliasOptions:
    try:
        return service.select_login_alias(payload.alias)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/reset", response_model=SessionSnapshot, dependencies=[Depends(require_mobile_token)])
def reset() -> SessionSnapshot:
    try:
        return service.reset()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/close", response_model=SessionSnapshot, dependencies=[Depends(require_mobile_token)])
def close_app() -> SessionSnapshot:
    try:
        return service.close_app()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/session/screenshot", dependencies=[Depends(require_mobile_token)])
def session_screenshot() -> Response:
    try:
        image = service.capture_screenshot_png()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not image:
        raise HTTPException(status_code=404, detail="iEterm screenshot is not available.")
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/query/flight", response_model=QueryResponse, dependencies=[Depends(require_mobile_token)])
def query_flight(payload: FlightQuery) -> QueryResponse:
    try:
        return service.query_flight(payload)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/query/international-fare", response_model=FareQueryResponse, dependencies=[Depends(require_mobile_token)])
def query_international_fare(payload: InternationalFareQuery) -> FareQueryResponse:
    try:
        return service.query_international_fare(payload)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/query/raw-command", response_model=RawCommandResponse, dependencies=[Depends(require_mobile_token)])
def query_raw_command(payload: RawCommandRequest) -> RawCommandResponse:
    try:
        return service.run_raw_query_command(payload)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/query/fare-calculation", response_model=FareCalculationResponse, dependencies=[Depends(require_mobile_token)])
def copy_fare_calculation() -> FareCalculationResponse:
    try:
        return service.copy_fare_calculation_text()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
