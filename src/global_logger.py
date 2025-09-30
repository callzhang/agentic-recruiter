"""
Global logger for Boss Zhipin automation.
This module provides a simple logging interface that can be used anywhere in the application.
"""

import logging
from typing import Optional

# Global logger instance
_global_logger: Optional[logging.Logger] = None

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels."""
    
    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Format the timestamp first
        record.asctime = self.formatTime(record, self.datefmt)
        
        # Get the color for this log level
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        
        # Add color attributes to the record
        record.color = color
        record.reset = reset
        
        # Use the parent formatter to handle the format string
        return super().format(record)


def get_logger() -> logging.Logger:
    """Get the global logger instance."""
    global _global_logger
    if _global_logger is None:
        # Create a default logger if none is set
        _global_logger = logging.getLogger("boss_service")
        _global_logger.setLevel(logging.INFO)
        if not _global_logger.handlers:
            handler = logging.StreamHandler()
            formatter = ColoredFormatter('%(asctime)s - %(color)s%(levelname)s%(reset)s - %(color)s%(message)s%(reset)s')
            handler.setFormatter(formatter)
            _global_logger.addHandler(handler)
    return _global_logger

