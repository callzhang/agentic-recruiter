#!/usr/bin/env python3
"""
Custom file watcher for boss server with polling-based monitoring.
Only watches files that belong to the boss server to avoid unnecessary restarts.
"""

import os
import time
import threading
from pathlib import Path
from typing import Set, List, Callable, Optional
import fnmatch


class BossServerFileWatcher:
    """Custom file watcher that only monitors boss server files using polling."""
    
    def __init__(self, 
                 include_patterns: List[str] = None,
                 exclude_patterns: List[str] = None,
                 poll_interval: float = 1.0,
                 callback: Optional[Callable] = None):
        """
        Initialize the file watcher.
        
        Args:
            include_patterns: List of file patterns to include
            exclude_patterns: List of file patterns to exclude
            poll_interval: How often to check for changes (seconds)
            callback: Function to call when changes are detected
        """
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []
        self.poll_interval = poll_interval
        self.callback = callback
        
        # Track file modification times
        self.file_mtimes: dict = {}
        self.running = False
        self.watch_thread: Optional[threading.Thread] = None
        
        # Default boss server patterns
        if not self.include_patterns:
            self.include_patterns = [
                "boss_service.py",
                "start_service.py",
                "boss_app.py", 
                "streamlit_shared.py",
                "src/*.py",
                "src/**/*.py",
                "pages/*.py",
                "config/*.yaml",
                "config/*.yml",
                "*.yaml",
                "*.yml"
            ]
        
        if not self.exclude_patterns:
            self.exclude_patterns = [
                "*.log",
                "*.tmp", 
                "*.cache",
                "__pycache__",
                ".git",
                "node_modules",
                "*.pyc",
                "*.pyo",
                "test_*",
                "*_test.py",
                "*.md",  # Exclude documentation files
                "docs/**",
                "*.ipynb",  # Exclude Jupyter notebooks
                "*.json",  # Exclude JSON files (except config)
                "data/**",  # Exclude data directory
                "output/**",  # Exclude output directory
            ]
    
    def _matches_pattern(self, filepath: str, patterns: List[str]) -> bool:
        """Check if file matches any of the given patterns."""
        for pattern in patterns:
            if fnmatch.fnmatch(filepath, pattern):
                return True
            # Also check relative path from current directory
            rel_path = os.path.relpath(filepath, os.getcwd())
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False
    
    def _should_watch_file(self, filepath: str) -> bool:
        """Determine if a file should be watched based on include/exclude patterns."""
        # Check if file matches any include pattern
        if not self._matches_pattern(filepath, self.include_patterns):
            return False
        
        # Check if file matches any exclude pattern
        if self._matches_pattern(filepath, self.exclude_patterns):
            return False
        
        return True
    
    def _get_files_to_watch(self) -> Set[str]:
        """Get all files that should be watched."""
        files_to_watch = set()
        
        # Walk through current directory and subdirectories
        for root, dirs, files in os.walk("."):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not self._matches_pattern(d, self.exclude_patterns)]
            
            for file in files:
                filepath = os.path.join(root, file)
                if self._should_watch_file(filepath):
                    files_to_watch.add(filepath)
        
        return files_to_watch
    
    def _check_for_changes(self) -> bool:
        """Check if any watched files have changed."""
        current_files = self._get_files_to_watch()
        
        # Check for new files
        for filepath in current_files:
            if filepath not in self.file_mtimes:
                self.file_mtimes[filepath] = 0  # New file, treat as changed
        
        # Check for modified files
        for filepath in list(self.file_mtimes.keys()):
            if filepath not in current_files:
                # File was deleted
                del self.file_mtimes[filepath]
                return True
            
            try:
                current_mtime = os.path.getmtime(filepath)
                if current_mtime != self.file_mtimes[filepath]:
                    self.file_mtimes[filepath] = current_mtime
                    return True
            except (OSError, FileNotFoundError):
                # File was deleted or moved
                del self.file_mtimes[filepath]
                return True
        
        return False
    
    def _watch_loop(self):
        """Main watching loop."""
        while self.running:
            try:
                if self._check_for_changes():
                    if self.callback:
                        self.callback()
                    break  # Exit after first change detected
                
                time.sleep(self.poll_interval)
            except Exception as e:
                print(f"Error in file watcher: {e}")
                time.sleep(self.poll_interval)
    
    def start(self):
        """Start watching for file changes."""
        if self.running:
            return
        
        self.running = True
        self.watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.watch_thread.start()
        print(f"Started boss server file watcher (polling every {self.poll_interval}s)")
        print(f"Watching {len(self.include_patterns)} include patterns")
        print(f"Excluding {len(self.exclude_patterns)} exclude patterns")
    
    def stop(self):
        """Stop watching for file changes."""
        self.running = False
        if self.watch_thread:
            self.watch_thread.join(timeout=1.0)


def create_boss_server_watcher(callback: Callable) -> BossServerFileWatcher:
    """Create a file watcher specifically for boss server files."""
    return BossServerFileWatcher(
        include_patterns=[
            "boss_service.py",
            "start_service.py",
            "boss_app.py",
            "streamlit_shared.py",
            "src/*.py",
            "src/**/*.py", 
            "pages/*.py",
            "config/*.yaml",
            "config/*.yml",
            "*.yaml",
            "*.yml"
        ],
        exclude_patterns=[
            "*.log",
            "*.tmp",
            "*.cache", 
            "__pycache__",
            ".git",
            "node_modules",
            "*.pyc",
            "*.pyo",
            "test_*",
            "*_test.py",
            "*.md",
            "docs/**",
            "*.ipynb",
            "*.json",
            "data/**",
            "output/**"
        ],
        poll_interval=1.0,
        callback=callback
    )


if __name__ == "__main__":
    # Test the file watcher
    def on_change():
        print("File change detected!")
    
    watcher = create_boss_server_watcher(on_change)
    watcher.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        print("File watcher stopped.")
