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
    PackageUpdates,
    PackageUpdatesReport,
)
from .notifier import Notifier
from .collector import collect_metrics, collect_package_updates

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


async def send_weekly_package_report():
    """Send weekly package updates report via ntfy."""
    global db, notifier, config
    
    if not db or not notifier or not config:
        logger.error("Database or notifier not initialized")
        return
    
    if not config.notifications.weekly_packages_enabled:
        logger.info("Weekly package report is disabled")
        return
    
    # Get current week identifier (YYYY-WW)
    now = datetime.utcnow()
    week_id = now.strftime("%Y-%W")
    
    # Check if already sent
    if db.was_weekly_report_sent(week_id):
        logger.info(f"Weekly package report already sent for week {week_id}")
        return
    
    logger.info("Generating weekly package report...")
    
    # Get all latest package updates
    all_updates = db.get_all_latest_package_updates()
    
    if not all_updates:
        logger.info("No package updates data available")
        return
    
    # Calculate totals
    total_packages = sum(u.total_count for u in all_updates)
    total_security = sum(u.security_updates for u in all_updates)
    
    # Build report
    report_lines = [
        f"📦 Report Settimanale Pacchetti",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 Settimana: {week_id}",
        f"🖥️ Sistemi: {len(all_updates)}",
        f"📊 Totale aggiornamenti: {total_packages}",
    ]
    
    if total_security > 0:
        report_lines.append(f"🔒 Aggiornamenti sicurezza: {total_security}")
    
    report_lines.append("")
    
    # Sort by number of updates (highest first)
    all_updates.sort(key=lambda x: x.total_count, reverse=True)
    
    for u in all_updates:
        status_emoji = "🔴" if u.total_count > 50 else "🟡" if u.total_count > 10 else "🟢"
        
        report_lines.append(f"┌─ {status_emoji} {u.hostname} ({u.client_id})")
        report_lines.append(f"│ Pacchetti: {u.total_count} ({u.package_manager})")
        
        if u.security_updates > 0:
            report_lines.append(f"│ 🔒 Sicurezza: {u.security_updates}")
        
        # Show top 5 packages to update
        if u.packages:
            report_lines.append(f"│ Top pacchetti:")
            for pkg in u.packages[:5]:
                report_lines.append(f"│   • {pkg.name}: {pkg.current_version} → {pkg.new_version}")
            
            if len(u.packages) > 5:
                report_lines.append(f"│   ... e altri {len(u.packages) - 5}")
        
        report_lines.append("└────────────────────────────")
        report_lines.append("")
    
    report_content = "\n".join(report_lines)
    
    # Determine priority based on total updates
    priority = "high" if total_security > 10 or total_packages > 100 else "default"
    
    # Send notification
    success = await notifier.send_notification(
        title=f"📦 Pacchetti da Aggiornare - {total_packages} totali",
        message=report_content,
        priority=priority,
        tags=["package", "arrow_up"]
    )
    
    if success:
        db.store_weekly_report(week_id, report_content, len(all_updates))
        logger.info(f"Weekly package report sent successfully for {len(all_updates)} clients")
    else:
        logger.error("Failed to send weekly package report")


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
        
        # Setup scheduler for weekly package reports
        if config.notifications.weekly_packages_enabled:
            day_map = {
                "monday": "mon", "tuesday": "tue", "wednesday": "wed",
                "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun"
            }
            day_of_week = day_map.get(config.notifications.weekly_packages_day.lower(), "mon")
            
            scheduler.add_job(
                send_weekly_package_report,
                CronTrigger(
                    day_of_week=day_of_week,
                    hour=config.notifications.weekly_packages_hour_utc,
                    minute=config.notifications.weekly_packages_minute_utc,
                    timezone="UTC"
                ),
                id="weekly_package_report",
                name="Weekly Package Updates Report",
                replace_existing=True
            )
            logger.info(f"Weekly package report scheduled for {config.notifications.weekly_packages_day} at {config.notifications.weekly_packages_hour_utc:02d}:{config.notifications.weekly_packages_minute_utc:02d} UTC")
        
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
    
    @app.post("/packages", response_model=PackageUpdatesReport)
    async def receive_package_updates(updates: PackageUpdates):
        """Receive package updates from a client."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        db.store_package_updates(updates)
        
        logger.info(f"Received package updates from {updates.client_id}: {updates.total_count} packages ({updates.security_updates} security)")
        
        return PackageUpdatesReport(
            status="ok",
            message=f"Package updates stored: {updates.total_count} packages",
            received_at=datetime.utcnow()
        )
    
    @app.get("/packages/{client_id}")
    async def get_package_updates(client_id: str):
        """Get latest package updates for a client."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        updates = db.get_latest_package_updates(client_id)
        if not updates:
            raise HTTPException(status_code=404, detail="No package updates found for this client")
        
        return updates
    
    @app.get("/packages")
    async def list_all_package_updates():
        """Get latest package updates for all clients."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        return db.get_all_latest_package_updates()
    
    @app.post("/test/daily-report")
    async def trigger_daily_report():
        """Manually trigger daily report (for testing)."""
        await send_daily_report()
        return {"status": "triggered"}
    
    @app.post("/test/weekly-report")
    async def trigger_weekly_report():
        """Manually trigger weekly package report (for testing)."""
        await send_weekly_package_report()
        return {"status": "triggered"}
    
    @app.post("/test/collect")
    async def test_collect():
        """Collect and store local metrics (for testing server as client too)."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        metrics = collect_metrics(config.client.client_id)
        db.store_metrics(metrics)
        
        return {"status": "collected", "client_id": metrics.client_id}
    
    @app.post("/test/collect-packages")
    async def test_collect_packages():
        """Collect and store local package updates (for testing)."""
        if not db:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        updates = collect_package_updates(config.client.client_id)
        if not updates:
            raise HTTPException(status_code=500, detail="Could not collect package updates")
        
        db.store_package_updates(updates)
        
        return {"status": "collected", "client_id": updates.client_id, "packages": updates.total_count}
    
    return app

