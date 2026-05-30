from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    """High-level session states exposed to the API layer."""

    LOGGED_OUT = "logged_out"
    LAUNCHING = "launching"
    LOGIN_SCREEN = "login_screen"
    LOGGING_IN = "logging_in"
    LOGGED_IN = "logged_in"
    SESSION_EXPIRED = "session_expired"
    ERROR = "error"


class FlightQuery(BaseModel):
    """Normalized query payload produced by the AI or external callers."""

    origin: str = Field(min_length=3, max_length=3, description="City or airport code")
    destination: str = Field(min_length=3, max_length=3, description="City or airport code")
    departure_date: date
    prefer_direct_only: bool = False


class FlightOption(BaseModel):
    """Single flight row parsed from the black-screen response."""

    flight_no: str
    depart_time: str
    arrive_time: str
    cabin: Optional[str] = None
    availability: Optional[str] = None


class InternationalFareQuery(BaseModel):
    """International fare lookup payload produced by AI or external callers."""

    origin: str = Field(min_length=3, max_length=3, description="City or airport code")
    destination: str = Field(min_length=3, max_length=3, description="City or airport code")
    departure_date: date
    airline: Optional[str] = Field(default=None, min_length=2, max_length=3, description="Optional airline code")
    passenger_type: str = Field(default="ADT", min_length=3, max_length=3, description="Passenger type code")


class FareOption(BaseModel):
    """Single fare row parsed from the black-screen response."""

    airline: Optional[str] = None
    fare_basis: Optional[str] = None
    cabin: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[str] = None
    rule: Optional[str] = None
    passenger_type: Optional[str] = None
    raw_line: str


class LoginAliasOptions(BaseModel):
    """Available login line aliases from the iEterm login dialog."""

    aliases: list[str] = Field(default_factory=list)
    selected_alias: Optional[str] = None


class SelectLoginAliasRequest(BaseModel):
    """Request payload for choosing one login line alias."""

    alias: str = Field(min_length=1, description="Login line alias shown in the iEterm dialog")


class SessionSnapshot(BaseModel):
    """Current session view returned by polling and login endpoints."""

    state: SessionState
    updated_at: datetime
    window_detected: bool = False
    last_command: Optional[str] = None
    note: Optional[str] = None


class QueryResponse(BaseModel):
    """API response for a completed flight availability query."""

    ok: bool
    session_state: SessionState
    issued_command: Optional[str] = None
    flights: list[FlightOption] = Field(default_factory=list)
    raw_text: str = ""
    error: Optional[str] = None


class FareQueryResponse(BaseModel):
    """API response for a completed international fare query."""

    ok: bool
    session_state: SessionState
    issued_command: Optional[str] = None
    fares: list[FareOption] = Field(default_factory=list)
    raw_text: str = ""
    error: Optional[str] = None


class RawCommandRequest(BaseModel):
    """Raw iEterm command entered by a trusted mobile user."""

    command: str = Field(min_length=1, max_length=200, description="Raw iEterm command")
    parse_fares: bool = True


class RawCommandResponse(BaseModel):
    """API response for a raw query command."""

    ok: bool
    session_state: SessionState
    issued_command: Optional[str] = None
    raw_text: str = ""
    fares: list[FareOption] = Field(default_factory=list)
    error: Optional[str] = None


class FareCalculationResponse(BaseModel):
    """API response for copied fare calculation popup text."""

    ok: bool
    session_state: SessionState
    raw_text: str = ""
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Minimal health-check payload."""

    service: str
    status: str
