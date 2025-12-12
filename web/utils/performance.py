"""Performance profiling utilities for web routes."""

import asyncio
import time
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
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        
        if self.duration_ms >= self.log_threshold_ms:
            self._log_results()
    
    def step(self, step_name: str):
        """Record a step with elapsed time since start."""
        if self.start_time is None:
            raise RuntimeError("Profiler not started. Use as context manager.")
        
        step_time = time.perf_counter()
        elapsed_ms = (step_time - self.start_time) * 1000
        
        self.steps.append({
            "name": step_name,
            "elapsed_ms": elapsed_ms,
            "timestamp": step_time
        })
        
        return elapsed_ms
    
    def _log_results(self):
        """Log profiling results."""
        if self.duration_ms is None:
            return
        
        # Build log message
        parts = [f"[PERF] {self.operation_name}: {self.duration_ms:.2f}ms total"]
        
        if self.steps:
            # Calculate step durations
            prev_time = self.start_time
            step_details = []
            for step in self.steps:
                step_duration = (step["timestamp"] - prev_time) * 1000
                step_details.append(f"{step['name']}={step_duration:.2f}ms")
                prev_time = step["timestamp"]
            
            parts.append(f"steps: {' -> '.join(step_details)}")
        
        logger.info(" ".join(parts))


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

