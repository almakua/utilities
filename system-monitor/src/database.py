"""SQLite database layer for metrics storage."""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import sqlite3

from .models import SystemMetrics, Alert, DailySummary, ClientInfo

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for system metrics."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()
    
    def _ensure_dir(self):
        """Ensure database directory exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    collected_at TIMESTAMP NOT NULL,
                    
                    -- CPU
                    cpu_percent REAL,
                    cpu_count INTEGER,
                    cpu_freq_mhz REAL,
                    
                    -- Temperature
                    cpu_temp_max REAL,
                    cpu_temp_time TIMESTAMP,
                    cpu_temp_available INTEGER,
                    
                    -- Memory
                    ram_total_gb REAL,
                    ram_used_gb REAL,
                    ram_available_gb REAL,
                    ram_percent REAL,
                    
                    -- Swap
                    swap_total_gb REAL,
                    swap_used_gb REAL,
                    swap_percent REAL,
                    
                    -- Disk (JSON array)
                    disk_partitions TEXT,
                    
                    -- Network
                    network_bytes_sent INTEGER,
                    network_bytes_recv INTEGER,
                    network_packets_sent INTEGER,
                    network_packets_recv INTEGER,
                    
                    -- System
                    uptime_seconds INTEGER,
                    process_count INTEGER,
                    load_avg_1 REAL,
                    load_avg_5 REAL,
                    load_avg_15 REAL,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_metrics_client_time 
                ON metrics(client_id, collected_at);
                
                CREATE INDEX IF NOT EXISTS idx_metrics_collected_at 
                ON metrics(collected_at);
                
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    current_value REAL,
                    threshold_value REAL,
                    recorded_at TIMESTAMP NOT NULL,
                    message TEXT,
                    notified INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_alerts_client_time 
                ON alerts(client_id, recorded_at);
                
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    metrics_count INTEGER DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date DATE NOT NULL,
                    sent_at TIMESTAMP NOT NULL,
                    client_count INTEGER,
                    report_content TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_daily_reports_date 
                ON daily_reports(report_date);
            """)
            conn.commit()
    
    def store_metrics(self, metrics: SystemMetrics) -> int:
        """Store metrics and return the row ID."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO metrics (
                    client_id, hostname, collected_at,
                    cpu_percent, cpu_count, cpu_freq_mhz,
                    cpu_temp_max, cpu_temp_time, cpu_temp_available,
                    ram_total_gb, ram_used_gb, ram_available_gb, ram_percent,
                    swap_total_gb, swap_used_gb, swap_percent,
                    disk_partitions,
                    network_bytes_sent, network_bytes_recv,
                    network_packets_sent, network_packets_recv,
                    uptime_seconds, process_count,
                    load_avg_1, load_avg_5, load_avg_15
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.client_id,
                metrics.hostname,
                metrics.collected_at.isoformat(),
                metrics.cpu_percent,
                metrics.cpu_count,
                metrics.cpu_freq_mhz,
                metrics.cpu_temperature.max_temp_celsius,
                metrics.cpu_temperature.recorded_at.isoformat() if metrics.cpu_temperature.max_temp_celsius else None,
                1 if metrics.cpu_temperature.available else 0,
                metrics.ram_total_gb,
                metrics.ram_used_gb,
                metrics.ram_available_gb,
                metrics.ram_percent,
                metrics.swap_total_gb,
                metrics.swap_used_gb,
                metrics.swap_percent,
                json.dumps([p.model_dump() for p in metrics.disk_partitions]),
                metrics.network_io.bytes_sent,
                metrics.network_io.bytes_recv,
                metrics.network_io.packets_sent,
                metrics.network_io.packets_recv,
                metrics.uptime_seconds,
                metrics.process_count,
                metrics.load_avg_1,
                metrics.load_avg_5,
                metrics.load_avg_15,
            ))
            
            # Update client info
            conn.execute("""
                INSERT INTO clients (client_id, hostname, first_seen, last_seen, metrics_count)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(client_id) DO UPDATE SET
                    hostname = excluded.hostname,
                    last_seen = excluded.last_seen,
                    metrics_count = metrics_count + 1
            """, (
                metrics.client_id,
                metrics.hostname,
                metrics.collected_at.isoformat(),
                metrics.collected_at.isoformat(),
            ))
            
            conn.commit()
            return cursor.lastrowid
    
    def store_alert(self, alert: Alert) -> int:
        """Store an alert and return the row ID."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO alerts (
                    client_id, hostname, metric_name,
                    current_value, threshold_value, recorded_at, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.client_id,
                alert.hostname,
                alert.metric_name,
                alert.current_value,
                alert.threshold_value,
                alert.recorded_at.isoformat(),
                alert.message,
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_unnotified_alerts(self) -> list[Alert]:
        """Get all alerts that haven't been notified yet."""
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM alerts WHERE notified = 0
                ORDER BY recorded_at ASC
            """).fetchall()
            
            return [Alert(
                client_id=row["client_id"],
                hostname=row["hostname"],
                metric_name=row["metric_name"],
                current_value=row["current_value"],
                threshold_value=row["threshold_value"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                message=row["message"],
            ) for row in rows]
    
    def mark_alerts_notified(self, before: datetime):
        """Mark all alerts before timestamp as notified."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE alerts SET notified = 1 
                WHERE recorded_at <= ? AND notified = 0
            """, (before.isoformat(),))
            conn.commit()
    
    def get_clients(self) -> list[ClientInfo]:
        """Get all registered clients."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM clients ORDER BY last_seen DESC").fetchall()
            
            return [ClientInfo(
                client_id=row["client_id"],
                hostname=row["hostname"],
                first_seen=datetime.fromisoformat(row["first_seen"]),
                last_seen=datetime.fromisoformat(row["last_seen"]),
                metrics_count=row["metrics_count"],
            ) for row in rows]
    
    def get_daily_summary(self, client_id: str, date: datetime) -> Optional[DailySummary]:
        """Get daily summary for a client."""
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        
        with self._get_connection() as conn:
            # Get client info
            client_row = conn.execute(
                "SELECT hostname FROM clients WHERE client_id = ?",
                (client_id,)
            ).fetchone()
            
            if not client_row:
                return None
            
            hostname = client_row["hostname"]
            
            # Get metrics for the day
            rows = conn.execute("""
                SELECT * FROM metrics 
                WHERE client_id = ? AND collected_at >= ? AND collected_at < ?
                ORDER BY collected_at ASC
            """, (client_id, start.isoformat(), end.isoformat())).fetchall()
            
            if not rows:
                return None
            
            # Calculate statistics
            cpu_values = [r["cpu_percent"] for r in rows]
            ram_values = [r["ram_percent"] for r in rows]
            temp_values = [r["cpu_temp_max"] for r in rows if r["cpu_temp_max"] is not None]
            load_values = [r["load_avg_1"] for r in rows]
            
            # Find max values with timestamps
            cpu_max_row = max(rows, key=lambda r: r["cpu_percent"])
            ram_max_row = max(rows, key=lambda r: r["ram_percent"])
            
            # Disk - find worst partition across all samples
            disk_max_percent = 0
            disk_max_partition = "N/A"
            for row in rows:
                partitions = json.loads(row["disk_partitions"])
                for p in partitions:
                    if p["percent_used"] > disk_max_percent:
                        disk_max_percent = p["percent_used"]
                        disk_max_partition = p["mountpoint"]
            
            # Network totals (difference between first and last)
            first_row = rows[0]
            last_row = rows[-1]
            network_sent = (last_row["network_bytes_sent"] - first_row["network_bytes_sent"]) / (1024**3)
            network_recv = (last_row["network_bytes_recv"] - first_row["network_bytes_recv"]) / (1024**3)
            
            # Alerts count for the day
            alerts_count = conn.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE client_id = ? AND recorded_at >= ? AND recorded_at < ?
            """, (client_id, start.isoformat(), end.isoformat())).fetchone()[0]
            
            # Temperature stats
            temp_max_row = None
            if temp_values:
                temp_max_row = max(
                    [r for r in rows if r["cpu_temp_max"] is not None],
                    key=lambda r: r["cpu_temp_max"]
                )
            
            return DailySummary(
                client_id=client_id,
                hostname=hostname,
                date=start.strftime("%Y-%m-%d"),
                
                cpu_avg=round(sum(cpu_values) / len(cpu_values), 1),
                cpu_max=round(max(cpu_values), 1),
                cpu_max_time=datetime.fromisoformat(cpu_max_row["collected_at"]),
                
                ram_avg_percent=round(sum(ram_values) / len(ram_values), 1),
                ram_max_percent=round(max(ram_values), 1),
                ram_max_time=datetime.fromisoformat(ram_max_row["collected_at"]),
                
                temp_avg=round(sum(temp_values) / len(temp_values), 1) if temp_values else None,
                temp_max=round(max(temp_values), 1) if temp_values else None,
                temp_max_time=datetime.fromisoformat(temp_max_row["collected_at"]) if temp_max_row else None,
                
                disk_max_percent=round(disk_max_percent, 1),
                disk_max_partition=disk_max_partition,
                
                network_sent_gb=round(max(0, network_sent), 2),
                network_recv_gb=round(max(0, network_recv), 2),
                
                load_avg_max=round(max(load_values), 2),
                
                uptime_hours=round(last_row["uptime_seconds"] / 3600, 1),
                
                alerts_count=alerts_count,
            )
    
    def cleanup_old_data(self, retention_days: int):
        """Delete metrics older than retention period."""
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        
        with self._get_connection() as conn:
            result = conn.execute(
                "DELETE FROM metrics WHERE collected_at < ?",
                (cutoff.isoformat(),)
            )
            deleted_metrics = result.rowcount
            
            result = conn.execute(
                "DELETE FROM alerts WHERE recorded_at < ?",
                (cutoff.isoformat(),)
            )
            deleted_alerts = result.rowcount
            
            conn.commit()
            
            logger.info(f"Cleanup: deleted {deleted_metrics} metrics and {deleted_alerts} alerts older than {retention_days} days")
    
    def store_daily_report(self, report_date: datetime, content: str, client_count: int):
        """Store record of sent daily report."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO daily_reports (report_date, sent_at, client_count, report_content)
                VALUES (?, ?, ?, ?)
            """, (
                report_date.strftime("%Y-%m-%d"),
                datetime.utcnow().isoformat(),
                client_count,
                content,
            ))
            conn.commit()
    
    def was_daily_report_sent(self, report_date: datetime) -> bool:
        """Check if daily report was already sent for this date."""
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT id FROM daily_reports WHERE report_date = ?
            """, (report_date.strftime("%Y-%m-%d"),)).fetchone()
            return row is not None

