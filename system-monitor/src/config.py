"""Configuration management."""
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """Server configuration."""
    host: str = "0.0.0.0"
    port: int = 8080
    
    
class ClientConfig(BaseModel):
    """Client configuration."""
    server_url: str = "http://localhost:8080"
    client_id: Optional[str] = None  # Auto-generated if not set
    collect_interval_minutes: int = 15


class NtfyConfig(BaseModel):
    """Ntfy.sh notification configuration."""
    enabled: bool = True
    server_url: str = "https://ntfy.sh"
    topic: str = "system-monitor"
    priority: str = "default"  # min, low, default, high, max
    

class AlertConfig(BaseModel):
    """Alert thresholds configuration."""
    cpu_percent: float = 90.0
    ram_percent: float = 90.0
    disk_percent: float = 85.0
    temperature_celsius: float = 80.0
    load_avg_multiplier: float = 2.0


class NotificationConfig(BaseModel):
    """Notification schedule configuration."""
    daily_report_hour_utc: int = 7
    daily_report_minute_utc: int = 0
    send_immediate_alerts: bool = True
    # Weekly package report
    weekly_packages_enabled: bool = True
    weekly_packages_day: str = "monday"  # monday, tuesday, etc.
    weekly_packages_hour_utc: int = 8
    weekly_packages_minute_utc: int = 0


class DatabaseConfig(BaseModel):
    """Database configuration."""
    path: str = "/data/system_monitor.db"
    retention_days: int = 30


class Config(BaseModel):
    """Main configuration."""
    mode: str = Field(default="client", description="'server' or 'client'")
    server: ServerConfig = Field(default_factory=ServerConfig)
    client: ClientConfig = Field(default_factory=ClientConfig)
    ntfy: NtfyConfig = Field(default_factory=NtfyConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from file and environment variables.
    
    Priority (highest to lowest):
    1. Environment variables (SYSMON_*)
    2. Config file
    3. Defaults
    """
    config_dict = {}
    
    # Load from file if exists
    if config_path is None:
        config_path = os.environ.get("SYSMON_CONFIG_PATH", "/config/config.yaml")
    
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file) as f:
            config_dict = yaml.safe_load(f) or {}
    
    # Override with environment variables
    env_overrides = {
        "SYSMON_MODE": ("mode", str),
        "SYSMON_SERVER_HOST": ("server.host", str),
        "SYSMON_SERVER_PORT": ("server.port", int),
        "SYSMON_SERVER_URL": ("client.server_url", str),
        "SYSMON_CLIENT_ID": ("client.client_id", str),
        "SYSMON_COLLECT_INTERVAL": ("client.collect_interval_minutes", int),
        "SYSMON_NTFY_ENABLED": ("ntfy.enabled", lambda x: x.lower() == "true"),
        "SYSMON_NTFY_SERVER": ("ntfy.server_url", str),
        "SYSMON_NTFY_TOPIC": ("ntfy.topic", str),
        "SYSMON_NTFY_PRIORITY": ("ntfy.priority", str),
        "SYSMON_ALERT_CPU": ("alerts.cpu_percent", float),
        "SYSMON_ALERT_RAM": ("alerts.ram_percent", float),
        "SYSMON_ALERT_DISK": ("alerts.disk_percent", float),
        "SYSMON_ALERT_TEMP": ("alerts.temperature_celsius", float),
        "SYSMON_DAILY_HOUR": ("notifications.daily_report_hour_utc", int),
        "SYSMON_WEEKLY_PKG_ENABLED": ("notifications.weekly_packages_enabled", lambda x: x.lower() == "true"),
        "SYSMON_WEEKLY_PKG_DAY": ("notifications.weekly_packages_day", str),
        "SYSMON_WEEKLY_PKG_HOUR": ("notifications.weekly_packages_hour_utc", int),
        "SYSMON_DB_PATH": ("database.path", str),
        "SYSMON_DB_RETENTION": ("database.retention_days", int),
    }
    
    for env_var, (path, converter) in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(config_dict, path, converter(value))
    
    return Config(**config_dict)


def _set_nested(d: dict, path: str, value) -> None:
    """Set a nested dictionary value using dot notation."""
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value

