from __future__ import annotations

import platform
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any

from .config import Settings
from .models import SessionState


class AutomationError(RuntimeError):
    """Raised when the desktop automation layer cannot reach a safe state."""


class IETermAutomation(ABC):
    """Stable interface used by the API/service layer."""

    @abstractmethod
    def detect_state(self) -> SessionState:
        raise NotImplementedError

    @abstractmethod
    def ensure_window(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def login(self) -> SessionState:
        raise NotImplementedError

    @abstractmethod
    def list_login_aliases(self) -> tuple[list[str], str | None]:
        raise NotImplementedError

    @abstractmethod
    def select_login_alias(self, alias: str) -> tuple[list[str], str | None]:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_screen_text(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> SessionState:
        raise NotImplementedError


class MockIETermAutomation(IETermAutomation):
    """Development backend that lets the API run without Windows or iEterm."""

    def __init__(self, sample_response: str, sample_fare_response: str) -> None:
        self._state = SessionState.LOGGED_IN
        self._sample_response = sample_response
        self._sample_fare_response = sample_fare_response
        self._last_command = ""
        self._login_aliases = ["can826-01", "BJS177", "can826-05", "can826-06", "584-02", "其他"]
        self._selected_alias = "can826-01"

    def detect_state(self) -> SessionState:
        return self._state

    def ensure_window(self) -> bool:
        return True

    def login(self) -> SessionState:
        self._state = SessionState.LOGGED_IN
        return self._state

    def list_login_aliases(self) -> tuple[list[str], str | None]:
        return self._login_aliases.copy(), self._selected_alias

    def select_login_alias(self, alias: str) -> tuple[list[str], str | None]:
        if alias not in self._login_aliases:
            raise AutomationError(f"Login alias '{alias}' was not found.")
        self._selected_alias = alias
        return self.list_login_aliases()

    def send_command(self, command: str) -> None:
        self._last_command = command

    def read_screen_text(self) -> str:
        if self._last_command.upper().startswith(("XS FSD", "FSD", "XS FSI", "FSI")):
            return self._sample_fare_response
        return self._sample_response

    def reset(self) -> SessionState:
        self._state = SessionState.LOGGED_IN
        return self._state


class WindowsIETermAutomation(IETermAutomation):
    """Windows desktop backend for a real iEterm client.

    This implementation is intentionally conservative:
    - window detection works by title/title regex
    - command entry uses keyboard input against the focused window
    - screen text extraction prefers clipboard, then falls back to descendant text
    - login is only attempted when explicit control ids/titles are configured
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._window: Any | None = None

    def _ensure_windows(self) -> None:
        if platform.system() != "Windows":
            raise AutomationError("WindowsIETermAutomation only runs on Windows hosts.")

    def detect_state(self) -> SessionState:
        self._ensure_windows()
        window = self._resolve_window()
        if window is None:
            return SessionState.LOGGED_OUT

        screen_text = self._read_window_text(window)
        if self._contains_any(screen_text, self._settings.login_keywords):
            return SessionState.LOGIN_SCREEN
        if self._contains_any(screen_text, self._settings.session_expired_keywords):
            return SessionState.SESSION_EXPIRED
        return SessionState.LOGGED_IN

    def ensure_window(self) -> bool:
        self._ensure_windows()
        window = self._resolve_window()
        if window is not None:
            self._focus_window(window)
            return True

        if not self._settings.executable_path:
            return False

        # Launch only when the executable path is explicitly configured.
        subprocess.Popen([self._settings.executable_path])
        deadline = time.monotonic() + self._settings.launch_timeout_seconds
        while time.monotonic() < deadline:
            window = self._resolve_window()
            if window is not None:
                self._focus_window(window)
                return True
            time.sleep(0.5)
        return False

    def login(self) -> SessionState:
        self._ensure_windows()
        if not self.ensure_window():
            return SessionState.LOGGED_OUT

        current_state = self.detect_state()
        if current_state == SessionState.LOGGED_IN:
            return current_state
        if not self._settings.auto_login_enabled:
            return current_state

        username = self._settings.username
        password = self._settings.password
        if not username or not password:
            raise AutomationError("Set IETERM_USERNAME and IETERM_PASSWORD before enabling auto login.")

        if not self._settings.username_control or not self._settings.password_control:
            raise AutomationError(
                "Set IETERM_USERNAME_CONTROL and IETERM_PASSWORD_CONTROL before enabling auto login."
            )

        window = self._require_window()
        self._fill_control(window, self._settings.username_control, username)
        self._fill_control(window, self._settings.password_control, password)

        # Some deployments expose a dedicated login button, others accept Enter.
        if self._settings.submit_control:
            self._click_control(window, self._settings.submit_control)
        else:
            self._focus_window(window)
            window.type_keys("{ENTER}", set_foreground=True)

        time.sleep(self._settings.post_action_delay_seconds)
        return self.detect_state()

    def list_login_aliases(self) -> tuple[list[str], str | None]:
        raise AutomationError("Login alias selection is currently implemented for macOS only.")

    def select_login_alias(self, alias: str) -> tuple[list[str], str | None]:
        raise AutomationError("Login alias selection is currently implemented for macOS only.")

    def send_command(self, command: str) -> None:
        self._ensure_windows()
        window = self._require_window()
        self._focus_window(window)
        # Black-screen clients are usually most reliable when driven by keyboard.
        window.type_keys(command, with_spaces=True, set_foreground=True)
        window.type_keys("{ENTER}", set_foreground=True)
        time.sleep(self._settings.post_action_delay_seconds)

    def read_screen_text(self) -> str:
        self._ensure_windows()
        return self._read_window_text(self._require_window())

    def reset(self) -> SessionState:
        self._ensure_windows()
        self._window = None
        return self.detect_state()

    def _resolve_window(self) -> Any | None:
        try:
            desktop = self._desktop()
            window = desktop.window(title=self._settings.window_title)
            if window.exists(timeout=0.2):
                self._window = window
                return window
        except Exception:
            pass

        try:
            desktop = self._desktop()
            window = desktop.window(title_re=self._settings.window_title_re)
            if window.exists(timeout=0.2):
                self._window = window
                return window
        except Exception:
            return None
        return None

    def _require_window(self) -> Any:
        window = self._resolve_window()
        if window is None:
            raise AutomationError("iEterm window was not found. Set IETERM_EXECUTABLE_PATH or open the client first.")
        return window

    def _focus_window(self, window: Any) -> None:
        try:
            window.set_focus()
        except Exception as exc:
            raise AutomationError("Failed to focus the iEterm window.") from exc

    def _read_window_text(self, window: Any) -> str:
        # Clipboard capture is the first choice because black-screen clients
        # often expose text there even when the visual tree is sparse.
        clipboard_text = self._read_by_clipboard(window)
        if clipboard_text.strip():
            return clipboard_text

        try:
            texts = [item.window_text() for item in window.descendants() if item.window_text()]
        except Exception:
            texts = []
        return "\n".join(texts)

    def _read_by_clipboard(self, window: Any) -> str:
        try:
            import pyperclip
        except Exception:
            return ""

        try:
            self._focus_window(window)
            pyperclip.copy("")
            window.type_keys("^a", set_foreground=True)
            window.type_keys("^c", set_foreground=True)
            time.sleep(self._settings.post_action_delay_seconds)
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def _fill_control(self, window: Any, control_name: str, value: str) -> None:
        control = self._find_control(window, control_name)
        try:
            control.set_edit_text(value)
        except Exception:
            control.type_keys("^a{BACKSPACE}", set_foreground=True)
            control.type_keys(value, with_spaces=True, set_foreground=True)

    def _click_control(self, window: Any, control_name: str) -> None:
        control = self._find_control(window, control_name)
        try:
            control.click_input()
        except Exception as exc:
            raise AutomationError(f"Failed to click control '{control_name}'.") from exc

    def _find_control(self, window: Any, control_name: str) -> Any:
        # We try both automation id and title because different iEterm wrappers
        # expose different selector types.
        candidates = [
            dict(auto_id=control_name),
            dict(title=control_name),
            dict(best_match=control_name),
        ]
        for kwargs in candidates:
            try:
                control = window.child_window(**kwargs)
                if control.exists(timeout=0.2):
                    return control
            except Exception:
                continue
        raise AutomationError(f"Control '{control_name}' was not found in the current iEterm window.")

    def _desktop(self) -> Any:
        try:
            from pywinauto import Desktop
        except Exception as exc:
            raise AutomationError("pywinauto is required for the Windows automation backend.") from exc
        return Desktop(backend=self._settings.pywinauto_backend)

    @staticmethod
    def _contains_any(text: str, raw_keywords: str) -> bool:
        normalized_text = text.lower()
        keywords = [keyword.strip().lower() for keyword in raw_keywords.split(",") if keyword.strip()]
        return any(keyword in normalized_text for keyword in keywords)


class MacOSIETermAutomation(IETermAutomation):
    """macOS desktop backend for the iEterm Mac client.

    The first version keeps to operations that are relatively stable across
    wrapped terminal-style apps: activate the app, paste a command, press Enter,
    then copy visible text back through the clipboard.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ensure_macos(self) -> None:
        if platform.system() != "Darwin":
            raise AutomationError("MacOSIETermAutomation only runs on macOS hosts.")

    def detect_state(self) -> SessionState:
        self._ensure_macos()
        if not self._is_app_running():
            return SessionState.LOGGED_OUT

        if self._has_login_dialog():
            return SessionState.LOGIN_SCREEN
        screen_text = self.read_screen_text()
        if self._contains_any(screen_text, self._settings.login_keywords):
            return SessionState.LOGIN_SCREEN
        if self._contains_any(screen_text, self._settings.session_expired_keywords):
            return SessionState.SESSION_EXPIRED
        return SessionState.LOGGED_IN

    def ensure_window(self) -> bool:
        self._ensure_macos()
        if self._is_app_running():
            self._activate_app()
            return True

        if self._settings.executable_path:
            subprocess.Popen(["open", self._settings.executable_path])
        else:
            subprocess.Popen(["open", "-a", self._settings.mac_app_name])

        deadline = time.monotonic() + self._settings.launch_timeout_seconds
        while time.monotonic() < deadline:
            if self._is_app_running():
                self._activate_app()
                return True
            time.sleep(0.5)
        return False

    def login(self) -> SessionState:
        self._ensure_macos()
        if not self.ensure_window():
            return SessionState.LOGGED_OUT

        current_state = self.detect_state()
        if current_state == SessionState.LOGGED_IN:
            return current_state
        if current_state not in {SessionState.LOGIN_SCREEN, SessionState.SESSION_EXPIRED}:
            return current_state

        self._click_login_button()
        deadline = time.monotonic() + self._settings.command_timeout_seconds
        while time.monotonic() < deadline:
            self._confirm_system_prompt_if_present(use_enter_fallback=True)
            state = self.detect_state()
            if state != SessionState.LOGIN_SCREEN:
                self._confirm_system_prompt_if_present(use_enter_fallback=False)
                return state
            time.sleep(0.5)
        return self.detect_state()

    def list_login_aliases(self) -> tuple[list[str], str | None]:
        self._ensure_macos()
        if not self.ensure_window():
            raise AutomationError("iEterm Mac app was not found.")

        selected_alias, aliases = self._read_login_alias_popup()
        if not aliases:
            raise AutomationError("No login alias options were found in the current iEterm dialog.")
        return aliases, selected_alias

    def select_login_alias(self, alias: str) -> tuple[list[str], str | None]:
        self._ensure_macos()
        if not self.ensure_window():
            raise AutomationError("iEterm Mac app was not found.")

        self._select_login_alias_popup(alias)
        return self.list_login_aliases()

    def send_command(self, command: str) -> None:
        self._ensure_macos()
        if not self.ensure_window():
            raise AutomationError(
                "iEterm Mac app was not found. Set IETERM_MAC_APP_NAME, "
                "IETERM_MAC_PROCESS_NAME, or IETERM_EXECUTABLE_PATH."
            )

        self._activate_app()
        self._paste_text(command)
        self._run_osascript(
            f'''
            tell application "{self._settings.mac_app_name}" to activate
            tell application "System Events"
                key code 36
            end tell
            '''
        )
        time.sleep(self._settings.post_action_delay_seconds)

    def read_screen_text(self) -> str:
        self._ensure_macos()
        if not self._is_app_running():
            return ""
        self._activate_app()
        return self._read_by_clipboard()

    def reset(self) -> SessionState:
        self._ensure_macos()
        return self.detect_state()

    def _activate_app(self) -> None:
        self._run_osascript(f'tell application "{self._settings.mac_app_name}" to activate')
        time.sleep(self._settings.post_action_delay_seconds)

    def _is_app_running(self) -> bool:
        process_name = self._settings.mac_process_name or self._settings.mac_app_name
        script = f'''
        tell application "System Events"
            return exists process "{process_name}"
        end tell
        '''
        return self._run_osascript(script).strip().lower() == "true"

    def _has_login_dialog(self) -> bool:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                if not (exists window 1) then return false
                repeat with uiElement in entire contents of window 1
                    try
                        if (class of uiElement as text) is "button" then
                            set itemName to name of uiElement as text
                            if itemName is "登 录" or itemName is "登录" then return true
                        end if
                    end try
                end repeat
                return false
            end tell
        end tell
        '''
        try:
            return self._run_osascript(script).strip().lower() == "true"
        except AutomationError:
            return False

    def _read_login_alias_popup(self) -> tuple[str | None, list[str]]:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                if not (exists window 1) then error "No iEterm window found."
                set targetPopup to pop up button 1 of group 6 of UI element 1 of scroll area 1 of UI element 1 of scroll area 1 of group 1 of group 1 of group 1 of window 1

                set selectedValue to ""
                try
                    set selectedValue to value of targetPopup as text
                on error
                    try
                        set selectedValue to title of targetPopup as text
                    end try
                end try

                click targetPopup
                delay 0.2
                set itemNames to {{}}
                try
                    set menuItems to menu items of menu 1 of group 1 of group 1 of window 1
                    repeat with menuItem in menuItems
                        try
                            set itemName to name of menuItem as text
                            if itemName is not "" then set end of itemNames to itemName
                        end try
                    end repeat
                end try
                key code 53

                set oldDelimiters to AppleScript's text item delimiters
                set AppleScript's text item delimiters to linefeed
                set joinedItems to itemNames as text
                set AppleScript's text item delimiters to oldDelimiters
                return selectedValue & linefeed & joinedItems
            end tell
        end tell
        '''
        output = self._run_osascript(script)
        lines = [line.strip() for line in output.splitlines()]
        if not lines:
            return None, []

        selected_alias = lines[0] or None
        aliases = [line for line in lines[1:] if line]
        return selected_alias, aliases

    def _select_login_alias_popup(self, alias: str) -> None:
        process_name = self._applescript_text(self._process_name())
        alias_value = self._applescript_text(alias)
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                if not (exists window 1) then error "No iEterm window found."
                set targetPopup to pop up button 1 of group 6 of UI element 1 of scroll area 1 of UI element 1 of scroll area 1 of group 1 of group 1 of group 1 of window 1
                click targetPopup
                delay 0.2
                try
                    click menu item "{alias_value}" of menu 1 of group 1 of group 1 of window 1
                on error
                    key code 53
                    error "Login alias not found: {alias_value}"
                end try
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _click_login_button(self) -> None:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                if not (exists window 1) then error "No iEterm window found."
                try
                    click button "登 录" of UI element 1 of scroll area 1 of UI element 1 of scroll area 1 of group 1 of group 1 of group 1 of window 1
                on error
                    try
                        click button "登录" of UI element 1 of scroll area 1 of UI element 1 of scroll area 1 of group 1 of group 1 of group 1 of window 1
                    on error
                        error "Login button was not found."
                    end try
                end try
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _confirm_system_prompt_if_present(self, *, use_enter_fallback: bool = False) -> None:
        process_name = self._applescript_text(self._process_name())
        enter_fallback = "key code 36" if use_enter_fallback else ""
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                if not (exists window 1) then return
                repeat with uiElement in entire contents of window 1
                    try
                        if (class of uiElement as text) is "button" then
                            set itemName to name of uiElement as text
                            if itemName is "确定" then
                                click uiElement
                                return
                            end if
                        end if
                    end try
                end repeat
                {enter_fallback}
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _paste_text(self, text: str) -> None:
        try:
            import pyperclip
        except Exception as exc:
            raise AutomationError("pyperclip is required for the macOS automation backend.") from exc

        pyperclip.copy(text)
        self._run_osascript(
            f'''
            tell application "{self._settings.mac_app_name}" to activate
            tell application "System Events"
                keystroke "v" using command down
            end tell
            '''
        )

    def _read_by_clipboard(self) -> str:
        try:
            import pyperclip
        except Exception:
            return ""

        try:
            pyperclip.copy("")
            self._run_osascript(
                f'''
                tell application "{self._settings.mac_app_name}" to activate
                tell application "System Events"
                    keystroke "a" using command down
                    keystroke "c" using command down
                end tell
                '''
            )
            time.sleep(self._settings.post_action_delay_seconds)
            return pyperclip.paste() or ""
        except Exception:
            return ""

    @staticmethod
    def _contains_any(text: str, raw_keywords: str) -> bool:
        normalized_text = text.lower()
        keywords = [keyword.strip().lower() for keyword in raw_keywords.split(",") if keyword.strip()]
        return any(keyword in normalized_text for keyword in keywords)

    def _process_name(self) -> str:
        return self._settings.mac_process_name or self._settings.mac_app_name

    @staticmethod
    def _applescript_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _run_osascript(script: str) -> str:
        try:
            completed = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise AutomationError(f"AppleScript automation failed: {detail}") from exc
        return completed.stdout


def build_automation(settings: Settings) -> IETermAutomation:
    """Choose the safest backend for the current runtime."""

    if settings.automation_backend == "mock":
        return MockIETermAutomation(settings.mock_screen_text, settings.mock_fare_screen_text)
    if settings.automation_backend == "windows":
        return WindowsIETermAutomation(settings)
    if settings.automation_backend == "macos":
        return MacOSIETermAutomation(settings)
    if platform.system() == "Windows":
        return WindowsIETermAutomation(settings)
    if platform.system() == "Darwin":
        return MacOSIETermAutomation(settings)
    return MockIETermAutomation(settings.mock_screen_text, settings.mock_fare_screen_text)
