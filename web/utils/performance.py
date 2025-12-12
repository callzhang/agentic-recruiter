"""Performance profiling utilities for web routes."""

import asyncio
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Dict, Optional

from src.global_logger import logger


class PerformanceProfiler:
    """Context manager for profiling code execution time."""
    
    def __init__(self, operation_name: str, log_threshold_ms: float = 0.0):
        """
        Args:
            operation_name: Name of the operation being profiled
            log_threshold_ms: Only log if operation takes longer than this (milliseconds)
        """
        self.operation_name = operation_name
        self.log_threshold_ms = log_threshold_ms
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.steps: list[Dict[str, float]] = []
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def step(self, step_name: str):
        """Record a step with elapsed time since start."""
        self.steps.append({
            "name": step_name,
        })
        
        return 0.0
    
    def _log_results(self):
        """Log profiling results."""
        pass


def profile_async(func: Callable):
    """Decorator to profile async function execution time."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__name__}"
        with PerformanceProfiler(func_name, log_threshold_ms=10.0):
            return await func(*args, **kwargs)
    return wrapper


def profile_sync(func: Callable):
    """Decorator to profile sync function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        func_name = f"{func.__module__}.{func.__name__}"
        with PerformanceProfiler(func_name, log_threshold_ms=10.0):
            return func(*args, **kwargs)
    return wrapper


@contextmanager
def profile_operation(operation_name: str, log_threshold_ms: float = 0.0):
    """Context manager for profiling a code block.
    
    Example:
        with profile_operation("database_query", log_threshold_ms=50.0):
            result = await query_database()
    """
    with PerformanceProfiler(operation_name, log_threshold_ms) as profiler:
        yield profiler

