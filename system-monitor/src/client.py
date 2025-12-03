"""Client for sending metrics to server."""
import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

import httpx

from .collector import collect_metrics, get_hostname
from .config import Config
from .models import MetricsReport

logger = logging.getLogger(__name__)


class MetricsClient:
    """Client that collects and sends metrics to the server."""
    
    def __init__(self, config: Config):
        self.config = config
        self.server_url = config.client.server_url.rstrip("/")
        self.client_id = config.client.client_id or get_hostname()
        self.interval_seconds = config.client.collect_interval_minutes * 60
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={"Content-Type": "application/json"}
            )
        return self._http_client
    
    async def send_metrics(self) -> bool:
        """Collect and send metrics to server."""
        try:
            # Collect metrics
            logger.info(f"Collecting metrics for {self.client_id}...")
            metrics = collect_metrics(self.client_id)
            
            # Send to server
            client = await self._get_client()
            response = await client.post(
                f"{self.server_url}/metrics",
                json=metrics.model_dump(mode="json")
            )
            
            if response.status_code == 200:
                report = MetricsReport(**response.json())
                logger.info(f"Metrics sent successfully: {report.message}")
                return True
            else:
                logger.error(f"Server returned {response.status_code}: {response.text}")
                return False
                
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to server {self.server_url}: {e}")
            return False
        except httpx.TimeoutException:
            logger.error(f"Timeout connecting to server {self.server_url}")
            return False
        except Exception as e:
            logger.exception(f"Error sending metrics: {e}")
            return False
    
    async def check_server_health(self) -> bool:
        """Check if server is reachable."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.server_url}/health", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
    
    async def run(self):
        """Run the metrics collection loop."""
        self._running = True
        
        logger.info(f"Starting metrics client")
        logger.info(f"  Client ID: {self.client_id}")
        logger.info(f"  Server URL: {self.server_url}")
        logger.info(f"  Interval: {self.config.client.collect_interval_minutes} minutes")
        
        # Initial health check
        if await self.check_server_health():
            logger.info("Server is reachable")
        else:
            logger.warning("Server is not reachable, will retry on first metrics send")
        
        # Send initial metrics
        await self.send_metrics()
        
        # Main loop
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if self._running:
                    await self.send_metrics()
            except asyncio.CancelledError:
                break
        
        # Cleanup
        if self._http_client:
            await self._http_client.aclose()
        
        logger.info("Metrics client stopped")
    
    def stop(self):
        """Stop the client loop."""
        self._running = False


async def run_client(config: Config):
    """Run the metrics client."""
    client = MetricsClient(config)
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        client.stop()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    await client.run()


if __name__ == "__main__":
    from .config import load_config
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    config = load_config()
    asyncio.run(run_client(config))

