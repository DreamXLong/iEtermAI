from __future__ import annotations

from datetime import date

from .automation_windows import IETermAutomation
from .config import Settings
from .models import (
    FareQueryResponse,
    FlightQuery,
    InternationalFareQuery,
    LoginAliasOptions,
    QueryResponse,
    RawCommandRequest,
    RawCommandResponse,
    SessionSnapshot,
    SessionState,
)
from .parser import parse_fare_options, parse_flight_options
from .session import SessionManager


class IETermService:
    """Orchestrates session management, desktop automation, and result parsing."""

    _BLOCKED_COMMAND_PREFIXES = {
        "ETDZ",
        "ETRF",
        "ETRY",
        "VT",
        "VT:",
        "SS",
        "SD",
        "NM",
        "CT",
        "SSR",
        "TKTL",
        "TKT",
        "OSI",
        "RMK",
        "XE",
        "XI",
        "ER",
        "RR",
        "RF",
    }
    _ALLOWED_COMMAND_PREFIXES = {
        "AV",
        "AV:",
        "FV",
        "FV:",
        "SK",
        "SK:",
        "FF",
        "FF:",
        "DSG",
        "DSG:",
        "FD",
        "FD:",
        "FSD",
        "FSN",
        "FSI",
        "XS",
        "CD",
        "CNTD",
        "DATE",
        "TIME",
        "WF",
        "CO",
        "CV",
        "HELP",
        "SIIF",
        "RT",
        "PAT",
    }

    def __init__(
        self,
        automation: IETermAutomation,
        session_manager: SessionManager,
        settings: Settings,
    ) -> None:
        self._automation = automation
        self._session = session_manager
        self._settings = settings

    def session_status(self) -> SessionSnapshot:
        """Poll the current client state without changing anything."""
        detected = self._automation.detect_state()
        return self._session.update(
            detected,
            window_detected=detected != SessionState.LOGGED_OUT,
        )

    def ensure_ready(self) -> SessionSnapshot:
        """Make sure the client is open and, when allowed, attempt login."""
        window_detected = self._automation.ensure_window()
        state = self._automation.detect_state()
        snapshot = self._session.update(
            state,
            window_detected=window_detected,
        )
        if state in {SessionState.LOGGED_OUT, SessionState.LOGIN_SCREEN, SessionState.SESSION_EXPIRED}:
            if not self._settings.auto_login_enabled:
                note = "Auto login disabled. Complete login manually or enable guarded login."
                return self._session.update(
                    state,
                    window_detected=window_detected,
                    note=note,
                )
            return self.login()
        return snapshot

    def login(self) -> SessionSnapshot:
        """Run the guarded login flow exposed by the automation backend."""
        self._session.update(SessionState.LOGGING_IN, window_detected=True)
        state = self._automation.login()
        return self._session.update(
            state,
            window_detected=True,
            note="Login completed by automation." if state == SessionState.LOGGED_IN else "Login did not reach logged_in state.",
        )

    def list_login_aliases(self) -> LoginAliasOptions:
        """Return available login line aliases from the current login dialog."""
        self._automation.ensure_window()
        aliases, selected_alias = self._automation.list_login_aliases()
        return LoginAliasOptions(aliases=aliases, selected_alias=selected_alias)

    def select_login_alias(self, alias: str) -> LoginAliasOptions:
        """Select one login line alias by visible name."""
        self._automation.ensure_window()
        aliases, selected_alias = self._automation.select_login_alias(alias)
        return LoginAliasOptions(aliases=aliases, selected_alias=selected_alias)

    def query_flight(self, payload: FlightQuery) -> QueryResponse:
        """Execute a single availability query and parse the returned screen text."""
        snapshot = self.ensure_ready()
        if snapshot.state != SessionState.LOGGED_IN:
            return QueryResponse(
                ok=False,
                session_state=snapshot.state,
                error=snapshot.note or "iEterm is not ready for queries.",
            )

        command = self._build_availability_command(payload.origin, payload.destination, payload.departure_date)
        self._automation.send_command(command)
        raw_text = self._automation.read_screen_text()
        flights = parse_flight_options(raw_text)
        self._session.update(
            SessionState.LOGGED_IN,
            window_detected=True,
            last_command=command,
            note="Query completed.",
        )
        return QueryResponse(
            ok=True,
            session_state=SessionState.LOGGED_IN,
            issued_command=command,
            flights=flights,
            raw_text=raw_text,
        )

    def query_international_fare(self, payload: InternationalFareQuery) -> FareQueryResponse:
        """Execute a single international fare query and parse the returned text."""
        snapshot = self.ensure_ready()
        if snapshot.state != SessionState.LOGGED_IN:
            return FareQueryResponse(
                ok=False,
                session_state=snapshot.state,
                error=snapshot.note or "iEterm is not ready for fare queries.",
            )

        command = self._build_international_fare_command(payload)
        self._automation.send_command(command)
        raw_text = self._automation.read_screen_text()
        fares = parse_fare_options(raw_text)
        self._session.update(
            SessionState.LOGGED_IN,
            window_detected=True,
            last_command=command,
            note="International fare query completed.",
        )
        return FareQueryResponse(
            ok=True,
            session_state=SessionState.LOGGED_IN,
            issued_command=command,
            fares=fares,
            raw_text=raw_text,
        )

    def run_raw_query_command(self, payload: RawCommandRequest) -> RawCommandResponse:
        """Execute a raw query-only command after command whitelist checks."""
        command = self._normalize_raw_command(payload.command)
        validation_error = self._validate_raw_query_command(command)
        if validation_error:
            return RawCommandResponse(
                ok=False,
                session_state=self._session.snapshot().state,
                error=validation_error,
            )

        snapshot = self.ensure_ready()
        if snapshot.state != SessionState.LOGGED_IN:
            return RawCommandResponse(
                ok=False,
                session_state=snapshot.state,
                error=snapshot.note or "iEterm is not ready for raw query commands.",
            )

        self._automation.send_command(command)
        raw_text = self._automation.read_screen_text()
        fares = parse_fare_options(raw_text) if payload.parse_fares else []
        self._session.update(
            SessionState.LOGGED_IN,
            window_detected=True,
            last_command=command,
            note="Raw query command completed.",
        )
        return RawCommandResponse(
            ok=True,
            session_state=SessionState.LOGGED_IN,
            issued_command=command,
            raw_text=raw_text,
            fares=fares,
        )

    def reset(self) -> SessionSnapshot:
        state = self._automation.reset()
        return self._session.update(state, window_detected=state != SessionState.LOGGED_OUT)

    def _build_availability_command(self, origin: str, destination: str, departure_date: date) -> str:
        # Keep command construction centralized so the same template is reused
        # by the API, CLI wrappers, and future tool integrations.
        return self._settings.availability_command_template.format(
            origin=origin.upper(),
            destination=destination.upper(),
            departure_date=departure_date.strftime("%d%b").upper(),
        )

    def _build_international_fare_command(self, payload: InternationalFareQuery) -> str:
        origin = payload.origin.upper()
        destination = payload.destination.upper()
        airline = payload.airline.upper() if payload.airline else ""
        passenger_type = payload.passenger_type.upper()
        return self._settings.international_fare_command_template.format(
            origin=origin,
            destination=destination,
            route=f"{origin}{destination}",
            departure_date=payload.departure_date.strftime("%d%b").upper(),
            airline=airline,
            airline_part=f"/{airline}" if airline else "",
            passenger_type=passenger_type,
        )

    def _normalize_raw_command(self, command: str) -> str:
        return " ".join(command.strip().split())

    def _validate_raw_query_command(self, command: str) -> str | None:
        upper_command = command.upper()
        first_token = self._command_prefix(upper_command)
        blocked_tokens = {token.rstrip(":") for token in self._BLOCKED_COMMAND_PREFIXES}
        if first_token in blocked_tokens:
            return f"Command '{first_token}' is blocked because it may change bookings or tickets."

        allowed_tokens = {token.rstrip(":") for token in self._ALLOWED_COMMAND_PREFIXES}
        if first_token not in allowed_tokens:
            return f"Command '{first_token}' is not in the query-only allowlist."

        return None

    def _command_prefix(self, upper_command: str) -> str:
        first_token = upper_command.split(maxsplit=1)[0] if upper_command else ""
        return first_token.split(":", 1)[0].rstrip(":")
