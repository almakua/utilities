"""Main entrypoint for system monitor."""
import asyncio
import logging
import sys

import uvicorn

from .config import load_config
from .client import run_client
from .server import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def run_server(config):
    """Run the server mode."""
    logger.info("Starting in SERVER mode")
    
    app = create_app(config)
    
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        access_log=True,
    )


def run_client_mode(config):
    """Run the client mode."""
    logger.info("Starting in CLIENT mode")
    asyncio.run(run_client(config))


def main():
    """Main entrypoint."""
    config = load_config()
    
    logger.info(f"System Monitor v1.0.0")
    logger.info(f"Mode: {config.mode}")
    
    if config.mode == "server":
        run_server(config)
    elif config.mode == "client":
        run_client_mode(config)
    else:
        logger.error(f"Unknown mode: {config.mode}. Use 'server' or 'client'")
        sys.exit(1)


if __name__ == "__main__":
    main()

