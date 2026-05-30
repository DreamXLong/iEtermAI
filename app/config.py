from __future__ import annotations

from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IETERM_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = "ieterm-agent"
    automation_backend: Literal["auto", "mock", "windows", "macos"] = "auto"
    window_title: str = "iEterm"
    window_title_re: str = ".*iEterm.*"
    mac_app_name: str = "iEterm Mac版"
    mac_process_name: Optional[str] = None
    executable_path: Optional[str] = None
    pywinauto_backend: Literal["uia", "win32"] = "uia"
    command_timeout_seconds: int = 15
    launch_timeout_seconds: int = 20
    post_action_delay_seconds: float = 0.5
    auto_login_enabled: bool = False
    mobile_access_token: Optional[str] = None
    availability_command_template: str = "AV {origin} {destination} {departure_date}"
    international_fare_command_template: str = "XS FSD {origin}{destination}{airline_part}"
    credential_target: str = "ieterm/default"
    username: Optional[str] = None
    password: Optional[str] = None
    username_control: Optional[str] = None
    password_control: Optional[str] = None
    submit_control: Optional[str] = None
    login_keywords: str = "登录,login,sign in,password"
    session_expired_keywords: str = "超时,expired,session expired,relogin,重新登录,用户异常,请重新登录"
    mock_screen_text: str = (
        "MU5101 0800 1015 Y9\n"
        "CA1501 0930 1145 Y4\n"
        "HO1257 1130 1345 M2"
    )
    mock_fare_screen_text: str = (
        "CA YRTCN Y CNY 3200 RULE 001 ADT\n"
        "CA MRTCN M CNY 2450 RULE 002 ADT\n"
        "JL KEE1Y K JPY 68000 RULE JP1 ADT"
    )


settings = Settings()
