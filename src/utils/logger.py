"""
Logger setup for structured logging
"""

import json
import logging

logging.basicConfig(level=logging.INFO)

class Logger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _format_log(self, message: str, **kwargs) -> str:
        """Format log message with metadata as JSON."""
        return json.dumps({"message": message, "service": self.name, **kwargs})

    def info(self, message: str, **kwargs) -> None:
        """Log info level message."""
        self.logger.info(self._format_log(message, **kwargs))

    def error(self, message: str, error: Exception = None, **kwargs) -> None:
        """Log error level message."""
        error_details = (
            {"error_type": error.__class__.__name__, "error_message": str(error)}
            if error
            else {"error_message": kwargs.get("error", "Unknown error")}
        )

        self.logger.error(self._format_log(message, **error_details, **kwargs))

    def warning(self, message: str, **kwargs) -> None:
        """Log warning level message."""
        self.logger.warning(self._format_log(message, **kwargs))

    def debug(self, message: str, **kwargs) -> None:
        """Log debug level message."""
        self.logger.debug(self._format_log(message, **kwargs))


def get_logger(name: str) -> Logger:
    """Get a configured logger instance."""
    return Logger(name)
