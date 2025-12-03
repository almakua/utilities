"""Data models for system metrics."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DiskPartition(BaseModel):
    """Disk partition metrics."""
    device: str
    mountpoint: str
    filesystem: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float


class NetworkIO(BaseModel):
    """Network I/O metrics."""
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int


class CPUTemperature(BaseModel):
    """CPU temperature with timestamp."""
    max_temp_celsius: Optional[float] = None
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    available: bool = True


class SystemMetrics(BaseModel):
    """Complete system metrics snapshot."""
    # Client identification
    client_id: str
    hostname: str
    
    # Timestamp
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    
    # CPU
    cpu_percent: float
    cpu_count: int
    cpu_freq_mhz: Optional[float] = None
    
    # Temperature
    cpu_temperature: CPUTemperature
    
    # Memory
    ram_total_gb: float
    ram_used_gb: float
    ram_available_gb: float
    ram_percent: float
    
    # Swap
    swap_total_gb: float
    swap_used_gb: float
    swap_percent: float
    
    # Disk
    disk_partitions: list[DiskPartition]
    
    # Network
    network_io: NetworkIO
    
    # System
    uptime_seconds: int
    process_count: int
    
    # Load average (1, 5, 15 min)
    load_avg_1: float
    load_avg_5: float
    load_avg_15: float


class MetricsReport(BaseModel):
    """Response from server after receiving metrics."""
    status: str
    message: str
    received_at: datetime


class AlertThresholds(BaseModel):
    """Configurable alert thresholds."""
    cpu_percent: float = 90.0
    ram_percent: float = 90.0
    disk_percent: float = 85.0
    temperature_celsius: float = 80.0
    load_avg_multiplier: float = 2.0  # Multiplied by CPU count


class Alert(BaseModel):
    """Alert for threshold breach."""
    client_id: str
    hostname: str
    metric_name: str
    current_value: float
    threshold_value: float
    recorded_at: datetime
    message: str


class DailySummary(BaseModel):
    """Daily summary for a single client."""
    client_id: str
    hostname: str
    date: str
    
    # CPU stats
    cpu_avg: float
    cpu_max: float
    cpu_max_time: Optional[datetime] = None
    
    # RAM stats
    ram_avg_percent: float
    ram_max_percent: float
    ram_max_time: Optional[datetime] = None
    
    # Temperature stats
    temp_avg: Optional[float] = None
    temp_max: Optional[float] = None
    temp_max_time: Optional[datetime] = None
    
    # Disk (worst partition)
    disk_max_percent: float
    disk_max_partition: str
    
    # Network totals
    network_sent_gb: float
    network_recv_gb: float
    
    # Load average
    load_avg_max: float
    
    # Uptime
    uptime_hours: float
    
    # Alerts count
    alerts_count: int = 0


class ClientInfo(BaseModel):
    """Client registration info."""
    client_id: str
    hostname: str
    first_seen: datetime
    last_seen: datetime
    metrics_count: int


class UpdatablePackage(BaseModel):
    """A package that can be updated."""
    name: str
    current_version: str
    new_version: str
    repository: Optional[str] = None


class PackageUpdates(BaseModel):
    """Package updates info from a client."""
    client_id: str
    hostname: str
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    package_manager: str  # apt, dnf, yum, pacman, zypper
    packages: list[UpdatablePackage]
    security_updates: int = 0  # Count of security-related updates
    
    @property
    def total_count(self) -> int:
        return len(self.packages)


class PackageUpdatesReport(BaseModel):
    """Response from server after receiving package updates."""
    status: str
    message: str
    received_at: datetime

