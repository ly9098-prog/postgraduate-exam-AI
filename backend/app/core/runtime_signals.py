"""Install process shutdown signals without loading role configuration."""

import asyncio
import logging
import signal


def install_role_signal_handlers(stop_event: asyncio.Event, logger: logging.Logger) -> None:
    """Install SIGTERM/SIGINT handlers that set the stop event."""
    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        if not stop_event.is_set():
            logger.info("Received shutdown signal, initiating graceful shutdown")
            stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Windows / some environments don't support add_signal_handler
            pass
        except Exception:
            logger.warning("Could not install signal handler for %s", sig)
