"""
Global logger for Boss Zhipin automation.
This module provides a simple logging interface that can be used anywhere in the application.
"""

import logging
import sys
import os
from typing import Optional

# Global logger instance
_global_logger: Optional[logging.Logger] = None


def _is_debugger_attached() -> bool:
    """Check if a debugger is attached to the current process.
    
    Detects common Python debuggers:
    - PyCharm (via sys.gettrace() or PYCHARM_HOSTED env var)
    - VS Code (via debugpy in sys.modules or VSCODE_PID env var)
    - pdb/ipdb (via sys.gettrace())
    - Any other debugger using sys.settrace()
    
    Returns:
        bool: True if a debugger is detected, False otherwise
    """
    # Check if a trace function is set (most reliable method)
    if sys.gettrace() is not None:
        return True
    
    # Check for PyCharm
    if os.environ.get("PYCHARM_HOSTED") == "1":
        return True
    if "pydevd" in sys.modules:
        return True
    
    # Check for VS Code
    if os.environ.get("VSCODE_PID"):
        return True
    if "debugpy" in sys.modules:
        return True
    
    # Check for other common debugger indicators
    if os.environ.get("PYTHONBREAKPOINT") and os.environ.get("PYTHONBREAKPOINT") != "0":
        return True
    
    return False


def get_logger() -> logging.Logger:
    """Get the global logger instance.
    
    Automatically sets logging level to DEBUG if a debugger is attached,
    otherwise uses INFO level for production.
    """
    global _global_logger
    if _global_logger is None:
        # Create a default logger if none is set
        _global_logger = logging.getLogger("boss_service")
        
        # Set logging level based on debugger attachment
        debugger_attached = _is_debugger_attached()
        _global_logger.setLevel(logging.DEBUG if debugger_attached else logging.INFO)
        
        # Only add handlers if none exist
        if not _global_logger.handlers:
            # Use colorlog for color support, but only for our logger
            import colorlog
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
            
            # Prevent propagation to root logger to avoid conflicts
            _global_logger.propagate = False
            
            # Log debug mode status (only after handler is set up)
            if debugger_attached:
                _global_logger.debug("Debugger detected - logging level set to DEBUG")
    return _global_logger


logger = get_logger()
if __name__ == "__main__":
    logger.info("Hello, world!")
    logger.error("Error message")
    logger.warning("Warning message")
    logger.debug("Debug message")