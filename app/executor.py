from __future__ import annotations

from datetime import date

from .automation_windows import IETermAutomation
from .config import Settings
from .models import (
    FareQueryResponse,
    FareCalculationResponse,
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
        if self._is_session_expired_text(raw_text):
            self._session.update(
                SessionState.SESSION_EXPIRED,
                window_detected=True,
                last_command=command,
                note="iEterm reported an abnormal user state. Login again before querying.",
            )
            return QueryResponse(
                ok=False,
                session_state=SessionState.SESSION_EXPIRED,
                issued_command=command,
                raw_text=raw_text,
                error="iEterm 提示用户异常，需要重新登录。",
            )
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
        if self._is_session_expired_text(raw_text):
            self._session.update(
                SessionState.SESSION_EXPIRED,
                window_detected=True,
                last_command=command,
                note="iEterm reported an abnormal user state. Login again before querying.",
            )
            return FareQueryResponse(
                ok=False,
                session_state=SessionState.SESSION_EXPIRED,
                issued_command=command,
                raw_text=raw_text,
                error="iEterm 提示用户异常，需要重新登录。",
            )
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
        """Execute a raw command entered by a trusted mobile user."""
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
        if self._is_session_expired_text(raw_text):
            self._session.update(
                SessionState.SESSION_EXPIRED,
                window_detected=True,
                last_command=command,
                note="iEterm reported an abnormal user state. Login again before querying.",
            )
            return RawCommandResponse(
                ok=False,
                session_state=SessionState.SESSION_EXPIRED,
                issued_command=command,
                raw_text=raw_text,
                error="iEterm 提示用户异常，需要重新登录。",
            )
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

    def copy_fare_calculation_text(self) -> FareCalculationResponse:
        """Click fare calculation and return the popup text copied by iEterm."""
        snapshot = self.ensure_ready()
        if snapshot.state != SessionState.LOGGED_IN:
            return FareCalculationResponse(
                ok=False,
                session_state=snapshot.state,
                error=snapshot.note or "iEterm is not ready for fare calculation.",
            )

        raw_text = self._automation.copy_fare_calculation_text()
        self._session.update(
            SessionState.LOGGED_IN,
            window_detected=True,
            note="Fare calculation popup copied.",
        )
        return FareCalculationResponse(
            ok=True,
            session_state=SessionState.LOGGED_IN,
            raw_text=raw_text,
        )

    def reset(self) -> SessionSnapshot:
        state = self._automation.reset()
        return self._session.update(state, window_detected=state != SessionState.LOGGED_OUT)

    def close_app(self) -> SessionSnapshot:
        """Close the desktop client and update the tracked session state."""
        state = self._automation.close_app()
        return self._session.update(
            state,
            window_detected=state != SessionState.LOGGED_OUT,
            note="iEterm closed by automation." if state == SessionState.LOGGED_OUT else "iEterm close was requested.",
        )

    def capture_screenshot_png(self) -> bytes:
        """Return a PNG screenshot of the current desktop client state."""
        return self._automation.capture_screenshot_png()

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
        return None if command else "Command cannot be empty."

    def _is_session_expired_text(self, text: str) -> bool:
        normalized_text = text.lower()
        keywords = [keyword.strip().lower() for keyword in self._settings.session_expired_keywords.split(",") if keyword.strip()]
        return any(keyword in normalized_text for keyword in keywords)

