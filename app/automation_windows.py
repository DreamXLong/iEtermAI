from __future__ import annotations

import platform
import subprocess
import tempfile
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

    @abstractmethod
    def close_app(self) -> SessionState:
        raise NotImplementedError

    @abstractmethod
    def capture_screenshot_png(self) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def copy_fare_calculation_text(self) -> str:
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

    def close_app(self) -> SessionState:
        self._state = SessionState.LOGGED_OUT
        return self._state

    def capture_screenshot_png(self) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00"
            b"\x05\xfe\x02\xfeA\xd1\x1d\xb5\x00\x00\x00\x00IEND"
            b"\xaeB`\x82"
        )

    def copy_fare_calculation_text(self) -> str:
        return "模拟票价计算内容"


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

    def close_app(self) -> SessionState:
        self._ensure_windows()
        window = self._resolve_window()
        if window is None:
            return SessionState.LOGGED_OUT
        window.close()
        time.sleep(self._settings.post_action_delay_seconds)
        self._window = None
        return self.detect_state()

    def capture_screenshot_png(self) -> bytes:
        raise AutomationError("Screenshot capture is currently implemented for macOS only.")

    def copy_fare_calculation_text(self) -> str:
        raise AutomationError("Fare calculation popup copy is currently implemented for macOS only.")

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

        window_contents = self._window_contents_text()
        if self._has_login_dialog(window_contents):
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
            self._confirm_system_prompt_if_present(use_enter_fallback=True)
            self._focus_terminal_input()
            return current_state
        if current_state == SessionState.SESSION_EXPIRED:
            self.close_app()
            if not self.ensure_window():
                return SessionState.LOGGED_OUT
            current_state = self.detect_state()
        if current_state not in {SessionState.LOGIN_SCREEN, SessionState.SESSION_EXPIRED}:
            return current_state

        self._click_login_button()
        deadline = time.monotonic() + self._settings.command_timeout_seconds
        while time.monotonic() < deadline:
            self._confirm_system_prompt_if_present(use_enter_fallback=True)
            state = self.detect_state()
            if state != SessionState.LOGIN_SCREEN:
                self._confirm_system_prompt_if_present(use_enter_fallback=True)
                self._focus_terminal_input()
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
        self._focus_terminal_input()
        self._paste_text(command)
        self._run_osascript(
            f'''
            tell application "{self._settings.mac_app_name}" to activate
            tell application "System Events"
                key code 76
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

    def close_app(self) -> SessionState:
        self._ensure_macos()
        if not self._is_app_running():
            return SessionState.LOGGED_OUT

        self._activate_app()
        self._request_app_close()
        deadline = time.monotonic() + self._settings.command_timeout_seconds
        while time.monotonic() < deadline:
            self._confirm_close_prompt_if_present()
            if not self._is_app_running():
                return SessionState.LOGGED_OUT
            time.sleep(0.5)
        return self.detect_state()

    def capture_screenshot_png(self) -> bytes:
        self._ensure_macos()
        try:
            if self._is_app_running():
                self._activate_app()
        except AutomationError:
            # A screenshot is still useful even when process detection is wrong.
            pass

        try:
            with tempfile.TemporaryDirectory() as screenshot_dir:
                screenshot_path = f"{screenshot_dir}/ieterm-screen.png"
                subprocess.run(["screencapture", "-x", screenshot_path], check=True, timeout=8)
                with open(screenshot_path, "rb") as screenshot:
                    return screenshot.read()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise AutomationError("Failed to capture the current screen. Check macOS Screen Recording permission.") from exc

    def copy_fare_calculation_text(self) -> str:
        self._ensure_macos()
        if not self.ensure_window():
            raise AutomationError("iEterm Mac app was not found.")

        self._activate_app()
        self._click_named_element_or_coordinate(
            "票价计算",
            coordinate_script=self._fare_calculation_coordinate_script(),
        )
        time.sleep(self._settings.post_action_delay_seconds)
        self._set_clipboard_text("")
        self._click_named_element_or_coordinate("复制内容")
        copied_text = self._wait_for_clipboard_text()
        if not copied_text:
            raise AutomationError("Fare calculation popup did not copy any text.")
        return copied_text

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

    def _window_contents_text(self) -> str:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                if not (exists window 1) then return ""
                return entire contents of window 1
            end tell
        end tell
        '''
        try:
            return self._run_osascript(script)
        except AutomationError:
            return ""

    def _has_login_dialog(self, window_contents: str | None = None) -> bool:
        contents = window_contents if window_contents is not None else self._window_contents_text()
        login_markers = (
            "Eterm登录信息",
            "别名：",
            "用户名：",
            "密码：",
            "服务器：",
            "登 录",
        )
        return any(marker in contents for marker in login_markers)

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
                    return
                end try
                try
                    click button "登录" of UI element 1 of scroll area 1 of UI element 1 of scroll area 1 of group 1 of group 1 of group 1 of window 1
                    return
                end try
                repeat with uiElement in entire contents of window 1
                    try
                        set itemName to name of uiElement as text
                        if itemName contains "登" and itemName contains "录" then
                            click uiElement
                            return
                        end if
                    end try
                end repeat
                error "Login button was not found."
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _focus_terminal_input(self) -> None:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "{self._settings.mac_app_name}" to activate
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                if not (exists window 1) then return
                try
                    set winPos to position of window 1
                    set winSize to size of window 1
                    set clickX to (item 1 of winPos) + ((item 1 of winSize) * 0.02)
                    set clickY to (item 2 of winPos) + ((item 2 of winSize) * 0.14)
                    click at {{clickX, clickY}}
                end try
                delay 0.1
                key code 53
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _click_named_element_or_coordinate(self, name: str, *, coordinate_script: str = "") -> None:
        process_name = self._applescript_text(self._process_name())
        element_name = self._applescript_text(name)
        script = f'''
        tell application "{self._settings.mac_app_name}" to activate
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                repeat with appWindow in windows
                    repeat with uiElement in entire contents of appWindow
                        try
                            set itemName to name of uiElement as text
                            if itemName is "{element_name}" or itemName contains "{element_name}" then
                                click uiElement
                                return
                            end if
                        end try
                    end repeat
                end repeat
                {coordinate_script}
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _fare_calculation_coordinate_script(self) -> str:
        return '''
                try
                    if not (exists window 1) then return
                    set winPos to position of window 1
                    set winSize to size of window 1
                    set clickX to (item 1 of winPos) + ((item 1 of winSize) * 0.40)
                    set clickY to (item 2 of winPos) + ((item 2 of winSize) * 0.82)
                    click at {clickX, clickY}
                end try
        '''

    def _request_app_close(self) -> None:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "{self._settings.mac_app_name}" to activate
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                delay 0.2
                try
                    if exists window 1 then
                        click button 1 of window 1
                        return
                    end if
                end try
                keystroke "q" using command down
            end tell
        end tell
        '''
        self._run_osascript(script)
        time.sleep(self._settings.post_action_delay_seconds)

    def _confirm_close_prompt_if_present(self) -> None:
        process_name = self._applescript_text(self._process_name())
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                if not (exists window 1) then return
                repeat with uiElement in entire contents of window 1
                    try
                        set itemName to name of uiElement as text
                        if itemName is "是" or itemName is "Yes" or itemName is "确定" then
                            click uiElement
                            return
                        end if
                    end try
                end repeat
                key code 36
            end tell
        end tell
        '''
        self._run_osascript(script)
        self._click_system_prompt_by_screenshot()
        time.sleep(self._settings.post_action_delay_seconds)

    def _confirm_system_prompt_if_present(self, *, use_enter_fallback: bool = False) -> None:
        process_name = self._applescript_text(self._process_name())
        enter_fallback = "key code 36" if use_enter_fallback else ""
        coordinate_fallback = self._confirm_prompt_coordinate_script() if use_enter_fallback else ""
        script = f'''
        tell application "System Events"
            tell process "{process_name}"
                set frontmost to true
                if not (exists window 1) then return
                repeat with uiElement in entire contents of window 1
                    try
                        set itemName to name of uiElement as text
                        if itemName is "确定" then
                            click uiElement
                            return
                        end if
                    end try
                end repeat
                {enter_fallback}
                delay 0.2
                {coordinate_fallback}
            end tell
        end tell
        '''
        self._run_osascript(script)
        if use_enter_fallback:
            self._click_system_prompt_by_screenshot()
        time.sleep(self._settings.post_action_delay_seconds)

    def _confirm_prompt_coordinate_script(self) -> str:
        # The login success prompt is drawn inside iEterm's canvas, so it does
        # not always expose a normal macOS button. The default "确定" button sits
        # near the center-left terminal panel; this click is a last-resort noop
        # when the prompt is absent.
        return '''
                try
                    set winPos to position of window 1
                    set winSize to size of window 1
                    set clickX to (item 1 of winPos) + ((item 1 of winSize) * 0.36)
                    set clickY to (item 2 of winPos) + ((item 2 of winSize) * 0.63)
                    click at {clickX, clickY}
                end try
        '''

    def _click_system_prompt_by_screenshot(self) -> None:
        """Find and click the drawn blue "确定" button when it is not an AX button."""
        swift_script = r'''
import Foundation
import CoreGraphics
import ImageIO

guard CommandLine.arguments.count > 1 else { exit(0) }
let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard
    let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
else { exit(0) }

let width = image.width
let height = image.height
let bytesPerRow = width * 4
var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)
guard let context = CGContext(
    data: &pixels,
    width: width,
    height: height,
    bitsPerComponent: 8,
    bytesPerRow: bytesPerRow,
    space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
) else { exit(0) }
context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))

func isPromptBlue(_ x: Int, _ y: Int) -> Bool {
    let offset = y * bytesPerRow + x * 4
    let r = pixels[offset]
    let g = pixels[offset + 1]
    let b = pixels[offset + 2]
    return b > 130 && g > 80 && b > r + 40 && g > r + 20
}

let minX = max(0, Int(Double(width) * 0.15))
let maxX = min(width - 1, Int(Double(width) * 0.80))
let minY = max(0, Int(Double(height) * 0.25))
let maxY = min(height - 1, Int(Double(height) * 0.80))
var visited = [UInt8](repeating: 0, count: width * height)
var best: (count: Int, minX: Int, minY: Int, maxX: Int, maxY: Int)?

for y in minY...maxY {
    for x in minX...maxX {
        let index = y * width + x
        if visited[index] != 0 || !isPromptBlue(x, y) { continue }

        var stack = [(x, y)]
        visited[index] = 1
        var count = 0
        var cMinX = x
        var cMaxX = x
        var cMinY = y
        var cMaxY = y

        while let (cx, cy) = stack.popLast() {
            count += 1
            cMinX = min(cMinX, cx)
            cMaxX = max(cMaxX, cx)
            cMinY = min(cMinY, cy)
            cMaxY = max(cMaxY, cy)
            for (nx, ny) in [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)] {
                if nx < minX || nx > maxX || ny < minY || ny > maxY { continue }
                let nIndex = ny * width + nx
                if visited[nIndex] != 0 || !isPromptBlue(nx, ny) { continue }
                visited[nIndex] = 1
                stack.append((nx, ny))
            }
        }

        let compWidth = cMaxX - cMinX + 1
        let compHeight = cMaxY - cMinY + 1
        if count > 100 && compWidth >= 20 && compWidth <= 220 && compHeight >= 10 && compHeight <= 90 {
            if best == nil || count > best!.count {
                best = (count, cMinX, cMinY, cMaxX, cMaxY)
            }
        }
    }
}

guard let target = best else { exit(0) }
let centerX = Double(target.minX + target.maxX) / 2.0
let centerY = Double(target.minY + target.maxY) / 2.0
let displayBounds = CGDisplayBounds(CGMainDisplayID())
let scaleX = Double(width) / Double(displayBounds.width)
let scaleY = Double(height) / Double(displayBounds.height)
let point = CGPoint(x: centerX / scaleX, y: centerY / scaleY)

let move = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)
let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
move?.post(tap: .cghidEventTap)
Thread.sleep(forTimeInterval: 0.05)
down?.post(tap: .cghidEventTap)
Thread.sleep(forTimeInterval: 0.08)
up?.post(tap: .cghidEventTap)
'''
        try:
            with tempfile.NamedTemporaryFile(suffix=".png") as screenshot:
                subprocess.run(["screencapture", "-x", screenshot.name], check=True)
                subprocess.run(
                    ["swift", "-", screenshot.name],
                    input=swift_script,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
        except Exception:
            # Screenshot clicking is only a last-resort fallback; keep login flow moving.
            return

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

    def _set_clipboard_text(self, text: str) -> None:
        try:
            import pyperclip
        except Exception as exc:
            raise AutomationError("pyperclip is required for the macOS automation backend.") from exc

        pyperclip.copy(text)

    def _wait_for_clipboard_text(self, *, timeout_seconds: float = 5.0) -> str:
        try:
            import pyperclip
        except Exception as exc:
            raise AutomationError("pyperclip is required for the macOS automation backend.") from exc

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            text = pyperclip.paste() or ""
            if text:
                return text
            time.sleep(0.2)
        return ""

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
