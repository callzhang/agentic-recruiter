"""
Example of how to use the global logger with module-level pattern.
"""

# Get logger once at module level (recommended pattern)
try:
    from .global_logger import get_logger
except ImportError:
    from global_logger import get_logger

logger = get_logger()

def some_function():
    """Example function showing how to use the module-level logger."""
    # Use standard Python logging pattern
    logger.info("This is an info message")
    logger.warning("This is a warning message") 
    logger.error("This is an error message")
    logger.debug("This is a debug message")

if __name__ == "__main__":
    some_function()
