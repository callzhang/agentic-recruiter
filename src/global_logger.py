"""
Global logger for Boss Zhipin automation.
This module provides a simple logging interface that can be used anywhere in the application.
"""

import logging
from typing import Optional
import colorlog

# Global logger instance
_global_logger: Optional[logging.Logger] = None


def get_logger() -> logging.Logger:
    """Get the global logger instance."""
    global _global_logger
    if _global_logger is None:
        # Create a default logger if none is set
        _global_logger = logging.getLogger("boss_service")
        _global_logger.setLevel(logging.INFO)
        if not _global_logger.handlers:
            handler = colorlog.StreamHandler()
            formatter = colorlog.ColoredFormatter(
                '%(log_color)s%(asctime)s - %(levelname)s - %(message)s%(reset)s',
                datefmt='%Y-%m-%d %H:%M:%S',
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'magenta',
                }
            )
            handler.setFormatter(formatter)
            _global_logger.addHandler(handler)
    return _global_logger

