from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .automation_windows import AutomationError, build_automation
from .config import settings
from .executor import IETermService
from .models import (
    FareQueryResponse,
    FlightQuery,
    HealthResponse,
    InternationalFareQuery,
    LoginAliasOptions,
    QueryResponse,
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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(service=settings.service_name, status="ok")


@app.get("/session/status", response_model=SessionSnapshot)
def session_status() -> SessionSnapshot:
    try:
        return service.session_status()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/ensure-ready", response_model=SessionSnapshot)
def ensure_ready() -> SessionSnapshot:
    try:
        return service.ensure_ready()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/login", response_model=SessionSnapshot)
def login() -> SessionSnapshot:
    try:
        return service.login()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/session/login-aliases", response_model=LoginAliasOptions)
def login_aliases() -> LoginAliasOptions:
    try:
        return service.list_login_aliases()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/login-alias", response_model=LoginAliasOptions)
def select_login_alias(payload: SelectLoginAliasRequest) -> LoginAliasOptions:
    try:
        return service.select_login_alias(payload.alias)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/session/reset", response_model=SessionSnapshot)
def reset() -> SessionSnapshot:
    try:
        return service.reset()
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/query/flight", response_model=QueryResponse)
def query_flight(payload: FlightQuery) -> QueryResponse:
    try:
        return service.query_flight(payload)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/query/international-fare", response_model=FareQueryResponse)
def query_international_fare(payload: InternationalFareQuery) -> FareQueryResponse:
    try:
        return service.query_international_fare(payload)
    except AutomationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
