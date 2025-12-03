"""System metrics collector using psutil."""
import os
import re
import shutil
import socket
import subprocess
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
    PackageUpdates,
    UpdatablePackage,
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


def _detect_package_manager() -> Optional[str]:
    """Detect the system's package manager."""
    managers = [
        ("apt", "/usr/bin/apt"),
        ("dnf", "/usr/bin/dnf"),
        ("yum", "/usr/bin/yum"),
        ("pacman", "/usr/bin/pacman"),
        ("zypper", "/usr/bin/zypper"),
    ]
    
    for name, path in managers:
        if shutil.which(name) or os.path.exists(path):
            return name
    
    return None


def _parse_apt_updates(output: str) -> tuple[list[UpdatablePackage], int]:
    """Parse apt list --upgradable output."""
    packages = []
    security_count = 0
    
    for line in output.strip().split("\n"):
        if not line or line.startswith("Listing") or line.startswith("WARNING"):
            continue
        
        # Format: package/repo version arch [upgradable from: old_version]
        # Example: curl/jammy-updates 7.81.0-1ubuntu1.15 amd64 [upgradable from: 7.81.0-1ubuntu1.14]
        match = re.match(r"^([^/]+)/(\S+)\s+(\S+)\s+\S+\s+\[upgradable from:\s+([^\]]+)\]", line)
        if match:
            name, repo, new_ver, old_ver = match.groups()
            packages.append(UpdatablePackage(
                name=name,
                current_version=old_ver,
                new_version=new_ver,
                repository=repo
            ))
            if "security" in repo.lower():
                security_count += 1
    
    return packages, security_count


def _parse_dnf_updates(output: str) -> tuple[list[UpdatablePackage], int]:
    """Parse dnf check-update output."""
    packages = []
    security_count = 0
    
    for line in output.strip().split("\n"):
        if not line or line.startswith("Last metadata"):
            continue
        
        # Format: package.arch    version    repository
        parts = line.split()
        if len(parts) >= 3:
            name_arch = parts[0]
            new_ver = parts[1]
            repo = parts[2] if len(parts) > 2 else "unknown"
            
            # Remove architecture from name
            name = name_arch.rsplit(".", 1)[0] if "." in name_arch else name_arch
            
            packages.append(UpdatablePackage(
                name=name,
                current_version="installed",
                new_version=new_ver,
                repository=repo
            ))
    
    return packages, security_count


def _parse_pacman_updates(output: str) -> tuple[list[UpdatablePackage], int]:
    """Parse pacman -Qu output."""
    packages = []
    
    for line in output.strip().split("\n"):
        if not line:
            continue
        
        # Format: package old_version -> new_version
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "->":
            packages.append(UpdatablePackage(
                name=parts[0],
                current_version=parts[1],
                new_version=parts[3],
                repository="pacman"
            ))
    
    return packages, 0


def _parse_zypper_updates(output: str) -> tuple[list[UpdatablePackage], int]:
    """Parse zypper list-updates output."""
    packages = []
    security_count = 0
    
    for line in output.strip().split("\n"):
        if not line or line.startswith("Loading") or line.startswith("Reading") or "|" not in line:
            continue
        
        # Skip header
        if "Name" in line and "Version" in line:
            continue
        
        # Format: S | Repository | Name | Current Version | Available Version | Arch
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            status = parts[0]
            repo = parts[1]
            name = parts[2]
            current = parts[3]
            available = parts[4]
            
            packages.append(UpdatablePackage(
                name=name,
                current_version=current,
                new_version=available,
                repository=repo
            ))
            
            if status.lower() == "s":  # Security update
                security_count += 1
    
    return packages, security_count


def collect_package_updates(client_id: Optional[str] = None) -> Optional[PackageUpdates]:
    """
    Collect information about upgradable packages.
    
    Args:
        client_id: Custom client identifier. If None, hostname is used.
    
    Returns:
        PackageUpdates object or None if package manager not found.
    """
    hostname = get_hostname()
    if client_id is None:
        client_id = hostname
    
    pkg_manager = _detect_package_manager()
    if not pkg_manager:
        logger.warning("No supported package manager found")
        return None
    
    packages: list[UpdatablePackage] = []
    security_count = 0
    
    try:
        if pkg_manager == "apt":
            # Update package list first (non-blocking, just check cache)
            subprocess.run(
                ["apt", "update"],
                capture_output=True,
                timeout=300,
                check=False
            )
            result = subprocess.run(
                ["apt", "list", "--upgradable"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False
            )
            if result.returncode == 0:
                packages, security_count = _parse_apt_updates(result.stdout)
        
        elif pkg_manager == "dnf":
            result = subprocess.run(
                ["dnf", "check-update", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False
            )
            # dnf check-update returns 100 if updates available, 0 if none
            if result.returncode in (0, 100):
                packages, security_count = _parse_dnf_updates(result.stdout)
        
        elif pkg_manager == "yum":
            result = subprocess.run(
                ["yum", "check-update", "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False
            )
            if result.returncode in (0, 100):
                packages, security_count = _parse_dnf_updates(result.stdout)  # Same format
        
        elif pkg_manager == "pacman":
            # Sync database first
            subprocess.run(
                ["pacman", "-Sy"],
                capture_output=True,
                timeout=120,
                check=False
            )
            result = subprocess.run(
                ["pacman", "-Qu"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False
            )
            if result.returncode == 0:
                packages, security_count = _parse_pacman_updates(result.stdout)
        
        elif pkg_manager == "zypper":
            result = subprocess.run(
                ["zypper", "--non-interactive", "list-updates"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False
            )
            if result.returncode == 0:
                packages, security_count = _parse_zypper_updates(result.stdout)
        
        logger.info(f"Found {len(packages)} upgradable packages ({security_count} security)")
        
        return PackageUpdates(
            client_id=client_id,
            hostname=hostname,
            collected_at=datetime.utcnow(),
            package_manager=pkg_manager,
            packages=packages,
            security_updates=security_count,
        )
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout checking for package updates with {pkg_manager}")
        return None
    except Exception as e:
        logger.exception(f"Error collecting package updates: {e}")
        return None


if __name__ == "__main__":
    # Test collection
    import json
    metrics = collect_metrics()
    print(json.dumps(metrics.model_dump(), indent=2, default=str))
    
    print("\n--- Package Updates ---")
    updates = collect_package_updates()
    if updates:
        print(json.dumps(updates.model_dump(), indent=2, default=str))

