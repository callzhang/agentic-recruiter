"""Runtime utility functions for system information and version checking."""

import subprocess
import sys
import platform
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from .global_logger import get_logger

logger = get_logger()


def get_repo_path() -> Path:
    """Get the repository root path.
    
    Returns:
        Path: Path to the repository root
    """
    # Assuming this file is in src/, go up one level to get repo root
    return Path(__file__).parent.parent


def get_git_commit(short: bool = True, repo_path: Optional[Path] = None) -> Optional[str]:
    """Get current git commit hash.
    
    Args:
        short: If True, return short hash (7 chars), else full hash
        repo_path: Optional repository path, defaults to repo root
        
    Returns:
        Optional[str]: Commit hash or None if git command fails
    """
    repo_path = repo_path or get_repo_path()
    
    try:
        format_str = "--short" if short else ""
        result = subprocess.run(
            ["git", "rev-parse", format_str, "HEAD"] if format_str else ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Failed to get git commit: {e}")
    
    return None


def get_git_branch(repo_path: Optional[Path] = None) -> str:
    """Get current git branch name.
    
    Args:
        repo_path: Optional repository path, defaults to repo root
        
    Returns:
        str: Branch name or "main" as fallback
    """
    repo_path = repo_path or get_repo_path()
    
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Failed to get git branch: {e}")
    
    return "main"


def get_git_remote_url(repo_path: Optional[Path] = None, convert_ssh_to_https: bool = True) -> Optional[str]:
    """Get git remote origin URL.
    
    Args:
        repo_path: Optional repository path, defaults to repo root
        convert_ssh_to_https: If True, convert SSH URLs to HTTPS format
        
    Returns:
        Optional[str]: Remote URL or None if git command fails
    """
    repo_path = repo_path or get_repo_path()
    
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            
            # Convert SSH URL to HTTPS if requested
            if convert_ssh_to_https and url.startswith("git@"):
                url = url.replace(":", "/").replace("git@", "https://").replace(".git", "")
            
            return url
    except Exception as e:
        logger.debug(f"Failed to get git remote URL: {e}")
    
    return None


def fetch_git_updates(branch: Optional[str] = None, repo_path: Optional[Path] = None) -> bool:
    """Fetch latest changes from remote repository.
    
    Args:
        branch: Branch to fetch (defaults to current branch)
        repo_path: Optional repository path, defaults to repo root
        
    Returns:
        bool: True if fetch succeeded, False otherwise
    """
    repo_path = repo_path or get_repo_path()
    branch = branch or get_git_branch(repo_path)
    
    try:
        result = subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=repo_path,
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"Failed to fetch git updates: {e}")
        return False


def get_git_remote_commit(branch: Optional[str] = None, repo_path: Optional[Path] = None, short: bool = True) -> Optional[str]:
    """Get remote git commit hash for a branch.
    
    Args:
        branch: Branch name (defaults to current branch)
        repo_path: Optional repository path, defaults to repo root
        short: If True, return short hash (7 chars), else full hash
        
    Returns:
        Optional[str]: Remote commit hash or None if git command fails
    """
    repo_path = repo_path or get_repo_path()
    branch = branch or get_git_branch(repo_path)
    
    try:
        format_str = "--short" if short else ""
        result = subprocess.run(
            ["git", "rev-parse", format_str, f"origin/{branch}"] if format_str else ["git", "rev-parse", f"origin/{branch}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Failed to get remote git commit: {e}")
    
    return None


def check_git_update_available(repo_path: Optional[Path] = None, auto_merge: bool = True) -> Dict[str, Any]:
    """Check if a new git version is available and optionally merge updates.
    
    Args:
        repo_path: Optional repository path, defaults to repo root
        auto_merge: If True, attempt to merge updates automatically
        
    Returns:
        dict: Version check result with keys:
            - has_update: Boolean indicating if update is available
            - current_commit: Current git commit hash (short)
            - remote_commit: Remote git commit hash (short)
            - current_branch: Current git branch
            - repo_url: Repository URL (HTTPS format)
            - merge_success: Boolean indicating if merge was successful (if attempted)
            - merge_error: Error message if merge failed (if attempted)
            - message: Optional message about the update
    """
    repo_path = repo_path or get_repo_path()
    
    try:
        # Get current commit and branch
        current_commit = get_git_commit(short=True, repo_path=repo_path)
        current_branch = get_git_branch(repo_path)
        
        # Fetch latest from remote
        fetch_success = fetch_git_updates(branch=current_branch, repo_path=repo_path)
        if not fetch_success:
            logger.warning("Failed to fetch git updates")
        
        # Get remote commit
        remote_commit = get_git_remote_commit(branch=current_branch, repo_path=repo_path, short=True)
        
        # Check if update is available
        has_update = False
        if current_commit and remote_commit and current_commit != remote_commit:
            # Check if remote is ahead
            try:
                result = subprocess.run(
                    ["git", "rev-list", "--count", f"{current_commit}..origin/{current_branch}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    ahead_count = int(result.stdout.strip() or "0")
                    has_update = ahead_count > 0
            except Exception:
                # If rev-list fails, assume update available if commits differ
                has_update = True
        
        # Get repository URL
        repo_url = get_git_remote_url(repo_path=repo_path, convert_ssh_to_https=True)
        
        merge_success = None
        merge_error = None
        message = None
        
        # Attempt to merge if update is available and auto_merge is enabled
        if has_update and auto_merge:
            try:
                # Check if there are uncommitted changes
                status_result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                has_uncommitted = bool(status_result.stdout.strip())
                
                if has_uncommitted:
                    merge_error = "存在未提交的更改，无法自动合并。请手动运行 start.command 更新。"
                    message = merge_error
                else:
                    # Try to merge
                    merge_result = subprocess.run(
                        ["git", "merge", f"origin/{current_branch}", "--no-edit"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if merge_result.returncode == 0:
                        merge_success = True
                        # Get new commit after merge
                        new_commit = get_git_commit(short=True, repo_path=repo_path)
                        message = f"✅ 代码已自动更新: {current_commit} → {new_commit}"
                        
                        # Send notification
                        try:
                            from .assistant_actions import send_dingtalk_notification
                            send_dingtalk_notification(
                                title="🔄 服务器自动更新成功",
                                message=f"本地服务器代码已自动更新\n\n**更新前:** {current_commit}\n**更新后:** {new_commit}\n**分支:** {current_branch}",
                                job_id=None
                            )
                        except Exception as notif_err:
                            logger.warning(f"Failed to send update notification: {notif_err}")
                    else:
                        merge_success = False
                        merge_error = merge_result.stderr.strip() or "合并失败，请手动运行 start.command 更新。"
                        message = f"⚠️ 自动合并失败: {merge_error}"
                        
                        # Send warning notification
                        try:
                            from .assistant_actions import send_dingtalk_notification
                            send_dingtalk_notification(
                                title="⚠️ 代码更新需要手动处理",
                                message=f"检测到新版本但自动合并失败\n\n**当前版本:** {current_commit}\n**远程版本:** {remote_commit}\n**错误:** {merge_error}\n\n请手动运行 `start.command` 更新代码。",
                                job_id=None
                            )
                        except Exception as notif_err:
                            logger.warning(f"Failed to send warning notification: {notif_err}")
            except Exception as merge_exc:
                merge_success = False
                merge_error = str(merge_exc)
                message = f"⚠️ 合并过程出错: {merge_error}。请手动运行 start.command 更新。"
                logger.error(f"Merge attempt failed: {merge_exc}")
        elif has_update:
            message = f"新版本可用 (远程: {remote_commit})"
        
        return {
            "has_update": has_update,
            "current_commit": current_commit,
            "remote_commit": remote_commit,
            "current_branch": current_branch,
            "repo_url": repo_url,
            "merge_success": merge_success,
            "merge_error": merge_error,
            "message": message
        }
    except Exception as e:
        logger.warning(f"Version check failed: {e}")
        return {
            "has_update": False,
            "current_commit": None,
            "remote_commit": None,
            "current_branch": None,
            "repo_url": None,
            "merge_success": None,
            "merge_error": None,
            "message": None
        }


def get_system_info() -> Dict[str, Any]:
    """Get system runtime information.
    
    Returns:
        dict: System information with keys:
            - platform: Operating system platform
            - platform_version: OS version
            - python_version: Python version
            - architecture: System architecture
            - timestamp: Current timestamp (ISO format)
    """
    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version.split()[0],
        "architecture": platform.machine(),
        "timestamp": datetime.now().isoformat()
    }


def get_runtime_info() -> Dict[str, Any]:
    """Get comprehensive runtime information including git and system info.
    
    Returns:
        dict: Runtime information combining git and system info
    """
    git_info = check_git_update_available()
    system_info = get_system_info()
    
    return {
        **system_info,
        "git": {
            "current_commit": git_info.get("current_commit"),
            "current_branch": git_info.get("current_branch"),
            "remote_commit": git_info.get("remote_commit"),
            "has_update": git_info.get("has_update"),
            "repo_url": git_info.get("repo_url")
        }
    }

