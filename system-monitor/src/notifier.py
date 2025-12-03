"""Ntfy.sh notification sender."""
import logging
from typing import Optional

import httpx

from .config import NtfyConfig

logger = logging.getLogger(__name__)


class Notifier:
    """Send notifications via ntfy.sh."""
    
    def __init__(self, config: NtfyConfig):
        self.config = config
        self.enabled = config.enabled
        self.url = f"{config.server_url.rstrip('/')}/{config.topic}"
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def send_notification(
        self,
        title: str,
        message: str,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
        click_url: Optional[str] = None,
    ) -> bool:
        """
        Send a notification via ntfy.sh.
        
        Args:
            title: Notification title
            message: Notification body
            priority: Priority level (min, low, default, high, max)
            tags: List of emoji tags
            click_url: URL to open on click
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.debug("Notifications disabled, skipping")
            return True
        
        headers = {
            "Title": title,
            "Priority": priority or self.config.priority,
        }
        
        if tags:
            headers["Tags"] = ",".join(tags)
        
        if click_url:
            headers["Click"] = click_url
        
        try:
            client = await self._get_client()
            response = await client.post(
                self.url,
                content=message.encode("utf-8"),
                headers=headers,
            )
            
            if response.status_code == 200:
                logger.info(f"Notification sent: {title}")
                return True
            else:
                logger.error(f"Failed to send notification: {response.status_code} - {response.text}")
                return False
                
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to ntfy server: {e}")
            return False
        except httpx.TimeoutException:
            logger.error("Timeout sending notification")
            return False
        except Exception as e:
            logger.exception(f"Error sending notification: {e}")
            return False
    
    async def send_alert(
        self,
        hostname: str,
        alert_type: str,
        message: str,
    ) -> bool:
        """Send an alert notification with high priority."""
        return await self.send_notification(
            title=f"⚠️ Alert: {hostname}",
            message=f"{alert_type}\n\n{message}",
            priority="high",
            tags=["warning", "rotating_light"],
        )
    
    async def send_daily_summary(
        self,
        date: str,
        summary: str,
        client_count: int,
    ) -> bool:
        """Send daily summary notification."""
        return await self.send_notification(
            title=f"📊 Daily Report - {date}",
            message=f"Monitorati: {client_count} sistemi\n\n{summary}",
            priority="default",
            tags=["chart_with_upwards_trend", "calendar"],
        )
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Standalone test
if __name__ == "__main__":
    import asyncio
    
    async def test():
        config = NtfyConfig(
            enabled=True,
            server_url="https://ntfy.sh",
            topic="test-system-monitor",
            priority="default"
        )
        
        notifier = Notifier(config)
        
        success = await notifier.send_notification(
            title="🧪 Test Notification",
            message="This is a test from system-monitor",
            tags=["test", "computer"]
        )
        
        print(f"Notification sent: {success}")
        await notifier.close()
    
    asyncio.run(test())

