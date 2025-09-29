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
        
        # Format the message with colors
        record.levelname = f"{color}{record.levelname}{reset}"
        record.msg = f"{color}{record.msg}{reset}"
        
        # Use a simpler format without the logger name
        return f"{record.asctime} - {record.levelname} - {record.msg}"


def get_logger() -> logging.Logger:
    """Get the global logger instance."""
    global _global_logger
    if _global_logger is None:
        # Create a default logger if none is set
        _global_logger = logging.getLogger("boss_service")
        _global_logger.setLevel(logging.INFO)
        if not _global_logger.handlers:
            handler = logging.StreamHandler()
            formatter = ColoredFormatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            _global_logger.addHandler(handler)
    return _global_logger

