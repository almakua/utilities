"""System metrics collector using psutil."""
import os
import socket
import time
from datetime import datetime
from typing import Optional
import logging

import psutil

from .models import (
    CPUTemperature,
    DiskPartition,
    NetworkIO,
    SystemMetrics,
)

logger = logging.getLogger(__name__)


def get_hostname() -> str:
    """Get system hostname."""
    return socket.gethostname()


def get_cpu_temperature() -> CPUTemperature:
    """
    Get maximum CPU temperature.
    
    Note: Temperature sensors may not be available on all systems.
    Requires lm-sensors on Linux.
    """
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return CPUTemperature(available=False)
        
        max_temp = None
        
        # Check common sensor names
        for name in ["coretemp", "k10temp", "cpu_thermal", "cpu-thermal", "acpitz"]:
            if name in temps:
                for entry in temps[name]:
                    if entry.current is not None:
                        if max_temp is None or entry.current > max_temp:
                            max_temp = entry.current
        
        # If no known sensor, try all available
        if max_temp is None:
            for sensor_list in temps.values():
                for entry in sensor_list:
                    if entry.current is not None:
                        if max_temp is None or entry.current > max_temp:
                            max_temp = entry.current
        
        if max_temp is not None:
            return CPUTemperature(
                max_temp_celsius=round(max_temp, 1),
                recorded_at=datetime.utcnow(),
                available=True
            )
        
        return CPUTemperature(available=False)
        
    except Exception as e:
        logger.warning(f"Failed to read CPU temperature: {e}")
        return CPUTemperature(available=False)


def get_disk_partitions() -> list[DiskPartition]:
    """Get metrics for all mounted partitions."""
    partitions = []
    
    for partition in psutil.disk_partitions(all=False):
        try:
            # Skip special filesystems
            if partition.fstype in ["squashfs", "tmpfs", "devtmpfs", "overlay"]:
                continue
            
            usage = psutil.disk_usage(partition.mountpoint)
            
            partitions.append(DiskPartition(
                device=partition.device,
                mountpoint=partition.mountpoint,
                filesystem=partition.fstype,
                total_gb=round(usage.total / (1024**3), 2),
                used_gb=round(usage.used / (1024**3), 2),
                free_gb=round(usage.free / (1024**3), 2),
                percent_used=usage.percent
            ))
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot access partition {partition.mountpoint}: {e}")
            continue
    
    return partitions


def get_network_io() -> NetworkIO:
    """Get network I/O statistics."""
    net_io = psutil.net_io_counters()
    
    return NetworkIO(
        bytes_sent=net_io.bytes_sent,
        bytes_recv=net_io.bytes_recv,
        packets_sent=net_io.packets_sent,
        packets_recv=net_io.packets_recv
    )


def get_uptime_seconds() -> int:
    """Get system uptime in seconds."""
    boot_time = psutil.boot_time()
    return int(time.time() - boot_time)


def get_load_average() -> tuple[float, float, float]:
    """Get system load average (1, 5, 15 minutes)."""
    try:
        load = os.getloadavg()
        return (round(load[0], 2), round(load[1], 2), round(load[2], 2))
    except (OSError, AttributeError):
        # Not available on Windows
        return (0.0, 0.0, 0.0)


def collect_metrics(client_id: Optional[str] = None) -> SystemMetrics:
    """
    Collect all system metrics.
    
    Args:
        client_id: Custom client identifier. If None, hostname is used.
    
    Returns:
        SystemMetrics object with all collected data.
    """
    hostname = get_hostname()
    
    if client_id is None:
        client_id = hostname
    
    # CPU metrics
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    
    try:
        cpu_freq = psutil.cpu_freq()
        cpu_freq_mhz = round(cpu_freq.current, 0) if cpu_freq else None
    except Exception:
        cpu_freq_mhz = None
    
    # Memory metrics
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    # Load average
    load_1, load_5, load_15 = get_load_average()
    
    return SystemMetrics(
        client_id=client_id,
        hostname=hostname,
        collected_at=datetime.utcnow(),
        
        # CPU
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        cpu_freq_mhz=cpu_freq_mhz,
        
        # Temperature
        cpu_temperature=get_cpu_temperature(),
        
        # Memory
        ram_total_gb=round(mem.total / (1024**3), 2),
        ram_used_gb=round(mem.used / (1024**3), 2),
        ram_available_gb=round(mem.available / (1024**3), 2),
        ram_percent=mem.percent,
        
        # Swap
        swap_total_gb=round(swap.total / (1024**3), 2),
        swap_used_gb=round(swap.used / (1024**3), 2),
        swap_percent=swap.percent,
        
        # Disk
        disk_partitions=get_disk_partitions(),
        
        # Network
        network_io=get_network_io(),
        
        # System
        uptime_seconds=get_uptime_seconds(),
        process_count=len(psutil.pids()),
        
        # Load
        load_avg_1=load_1,
        load_avg_5=load_5,
        load_avg_15=load_15,
    )


if __name__ == "__main__":
    # Test collection
    import json
    metrics = collect_metrics()
    print(json.dumps(metrics.model_dump(), indent=2, default=str))

