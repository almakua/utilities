"""REST API server for receiving and storing metrics."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .config import Config
from .database import Database
from .models import (
    Alert,
    AlertThresholds,
    ClientInfo,
    DailySummary,
    MetricsReport,
    SystemMetrics,
)
from .notifier import Notifier
from .collector import collect_metrics

logger = logging.getLogger(__name__)

# Global instances
db: Optional[Database] = None
notifier: Optional[Notifier] = None
config: Optional[Config] = None
scheduler: Optional[AsyncIOScheduler] = None


def check_thresholds(metrics: SystemMetrics, thresholds: AlertThresholds) -> list[Alert]:
    """Check metrics against thresholds and return any alerts."""
    alerts = []
    now = datetime.utcnow()
    
    # CPU check
    if metrics.cpu_percent > thresholds.cpu_percent:
        alerts.append(Alert(
            client_id=metrics.client_id,
            hostname=metrics.hostname,
            metric_name="cpu_percent",
            current_value=metrics.cpu_percent,
            threshold_value=thresholds.cpu_percent,
            recorded_at=now,
            message=f"🔥 CPU alto: {metrics.cpu_percent}% (soglia: {thresholds.cpu_percent}%)"
        ))
    
    # RAM check
    if metrics.ram_percent > thresholds.ram_percent:
        alerts.append(Alert(
            client_id=metrics.client_id,
            hostname=metrics.hostname,
            metric_name="ram_percent",
            current_value=metrics.ram_percent,
            threshold_value=thresholds.ram_percent,
            recorded_at=now,
            message=f"💾 RAM alta: {metrics.ram_percent}% (soglia: {thresholds.ram_percent}%)"
        ))
    
    # Disk check (all partitions)
    for partition in metrics.disk_partitions:
        if partition.percent_used > thresholds.disk_percent:
            alerts.append(Alert(
                client_id=metrics.client_id,
                hostname=metrics.hostname,
                metric_name=f"disk_{partition.mountpoint}",
                current_value=partition.percent_used,
                threshold_value=thresholds.disk_percent,
                recorded_at=now,
                message=f"💿 Disco pieno {partition.mountpoint}: {partition.percent_used}% (soglia: {thresholds.disk_percent}%)"
            ))
    
    # Temperature check
    if metrics.cpu_temperature.available and metrics.cpu_temperature.max_temp_celsius:
        if metrics.cpu_temperature.max_temp_celsius > thresholds.temperature_celsius:
            alerts.append(Alert(
                client_id=metrics.client_id,
                hostname=metrics.hostname,
                metric_name="cpu_temperature",
                current_value=metrics.cpu_temperature.max_temp_celsius,
                threshold_value=thresholds.temperature_celsius,
                recorded_at=now,
                message=f"🌡️ Temperatura alta: {metrics.cpu_temperature.max_temp_celsius}°C (soglia: {thresholds.temperature_celsius}°C)"
            ))
    
    # Load average check
    load_threshold = thresholds.load_avg_multiplier * metrics.cpu_count
    if metrics.load_avg_1 > load_threshold:
        alerts.append(Alert(
            client_id=metrics.client_id,
            hostname=metrics.hostname,
            metric_name="load_avg",
            current_value=metrics.load_avg_1,
            threshold_value=load_threshold,
            recorded_at=now,
            message=f"⚡ Load alto: {metrics.load_avg_1} (soglia: {load_threshold})"
        ))
    
    return alerts


async def send_daily_report():
    """Send daily summary report via ntfy."""
    global db, notifier, config
    
    if not db or not notifier or not config:
        logger.error("Database or notifier not initialized")
        return
    
    yesterday = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Check if already sent
    if db.was_daily_report_sent(yesterday):
        logger.info("Daily report already sent for today")
        return
    
    logger.info("Generating daily report...")
    
    clients = db.get_clients()
    if not clients:
        logger.info("No clients registered, skipping daily report")
        return
    
    summaries: list[DailySummary] = []
    for client in clients:
        summary = db.get_daily_summary(client.client_id, yesterday)
        if summary:
            summaries.append(summary)
    
    if not summaries:
        logger.info("No metrics for yesterday, skipping daily report")
        return
    
    # Build report
    report_lines = [
        f"📊 Report Giornaliero - {yesterday.strftime('%Y-%m-%d')}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🖥️ Sistemi monitorati: {len(summaries)}",
        ""
    ]
    
    for s in summaries:
        report_lines.extend([
            f"┌─ {s.hostname} ({s.client_id})",
            f"│ CPU: avg {s.cpu_avg}% | max {s.cpu_max}%",
            f"│ RAM: avg {s.ram_avg_percent}% | max {s.ram_max_percent}%",
        ])
        
        if s.temp_max is not None:
            report_lines.append(f"│ Temp: avg {s.temp_avg}°C | max {s.temp_max}°C")
        
        report_lines.extend([
            f"│ Disco: max {s.disk_max_percent}% ({s.disk_max_partition})",
            f"│ Network: ↑{s.network_sent_gb:.2f}GB ↓{s.network_recv_gb:.2f}GB",
            f"│ Load max: {s.load_avg_max} | Uptime: {s.uptime_hours:.1f}h",
        ])
        
        if s.alerts_count > 0:
            report_lines.append(f"│ ⚠️ Alert: {s.alerts_count}")
        
        report_lines.append("└─────────────────────────")
        report_lines.append("")
    
    report_content = "\n".join(report_lines)
    
    # Send notification
    success = await notifier.send_notification(
        title=f"📊 Report Sistema - {yesterday.strftime('%d/%m/%Y')}",
        message=report_content,
        priority="default",
        tags=["chart_with_upwards_trend", "computer"]
    )
    
    if success:
        db.store_daily_report(yesterday, report_content, len(summaries))
        logger.info(f"Daily report sent successfully for {len(summaries)} clients")
    else:
        logger.error("Failed to send daily report")
    
    # Cleanup old data
    db.cleanup_old_data(config.database.retention_days)


async def send_immediate_alert(alert: Alert):
    """Send immediate alert notification."""
    global notifier, config
    
    if not notifier or not config or not config.notifications.send_immediate_alerts:
        return
    
    await notifier.send_notification(
        title=f"⚠️ Alert: {alert.hostname}",
        message=alert.message,
        priority="high",
        tags=["warning", "computer"]
    )


def create_app(app_config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    global db, notifier, config, scheduler
    
    config = app_config
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global db, notifier, scheduler
        
        # Startup
        logger.info("Starting System Monitor Server...")
        
        db = Database(config.database.path)
        notifier = Notifier(config.ntfy)
        
        # Setup scheduler for daily reports
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            send_daily_report,
            CronTrigger(
                hour=config.notifications.daily_report_hour_utc,
                minute=config.notifications.daily_report_minute_utc,
                timezone="UTC"
            ),
            id="daily_report",
            name="Daily System Report",
            replace_existing=True
        )
        scheduler.start()
        
        logger.info(f"Daily report scheduled at {config.notifications.daily_report_hour_utc:02d}:{config.notifications.daily_report_minute_utc:02d} UTC")
        
        yield
        
        # Shutdown
        if scheduler:
            scheduler.shutdown()
        logger.info("Server stopped")
    
    app = FastAPI(
        title="System Monitor Server",
        description="Collects and aggregates system metrics from multiple clients",
        version="1.0.0",
        lifespan=lifespan
    )
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    @app.post("/metrics", response_model=MetricsReport)
    async def receive_metrics(metrics: SystemMetrics):
        """Receive metrics from a client."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        # Store metrics
        db.store_metrics(metrics)
        
        # Check thresholds
        thresholds = AlertThresholds(
            cpu_percent=config.alerts.cpu_percent,
            ram_percent=config.alerts.ram_percent,
            disk_percent=config.alerts.disk_percent,
            temperature_celsius=config.alerts.temperature_celsius,
            load_avg_multiplier=config.alerts.load_avg_multiplier,
        )
        
        alerts = check_thresholds(metrics, thresholds)
        
        for alert in alerts:
            db.store_alert(alert)
            await send_immediate_alert(alert)
        
        logger.info(f"Received metrics from {metrics.client_id} ({metrics.hostname}), alerts: {len(alerts)}")
        
        return MetricsReport(
            status="ok",
            message=f"Metrics stored successfully. Alerts: {len(alerts)}",
            received_at=datetime.utcnow()
        )
    
    @app.get("/clients", response_model=list[ClientInfo])
    async def list_clients():
        """List all registered clients."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        return db.get_clients()
    
    @app.get("/clients/{client_id}/summary", response_model=Optional[DailySummary])
    async def get_client_summary(
        client_id: str,
        date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")
    ):
        """Get daily summary for a client."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.utcnow()
        
        summary = db.get_daily_summary(client_id, target_date)
        if not summary:
            raise HTTPException(status_code=404, detail="No data found for this client/date")
        
        return summary
    
    @app.get("/alerts")
    async def get_alerts(
        client_id: Optional[str] = None,
        limit: int = Query(100, ge=1, le=1000)
    ):
        """Get recent alerts."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        alerts = db.get_unnotified_alerts()
        
        if client_id:
            alerts = [a for a in alerts if a.client_id == client_id]
        
        return alerts[:limit]
    
    @app.post("/test/daily-report")
    async def trigger_daily_report():
        """Manually trigger daily report (for testing)."""
        await send_daily_report()
        return {"status": "triggered"}
    
    @app.post("/test/collect")
    async def test_collect():
        """Collect and store local metrics (for testing server as client too)."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        metrics = collect_metrics(config.client.client_id)
        db.store_metrics(metrics)
        
        return {"status": "collected", "client_id": metrics.client_id}
    
    return app

