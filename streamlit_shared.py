"""Shared utilities for the Streamlit control console."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import requests
import streamlit as st
import yaml



DEFAULT_BASE_URL = os.environ.get("BOSS_SERVICE_BASE_URL", "http://127.0.0.1:5001")
DEFAULT_CRITERIA_PATH = Path(os.environ.get("BOSS_CRITERIA_PATH", "config/jobs.yaml"))

# Session State Keys - Centralized management
# 
# This class centralizes all Streamlit session state keys used across the application.
# Keys are organized by functional area with detailed comments explaining their purpose.
# 
# REMOVED UNNECESSARY KEYS:
# - RECOMMEND_GREET_MESSAGE: Legacy from greeting generation (now uses analysis)
# - FIRST_ROLE_*, NEW_ROLE_*: Only used to clear inputs (Streamlit handles this automatically)
# - BASE_URL_*, CONFIG_PATH_SELECT, JOB_SELECTOR: Widget keys (Streamlit auto-generates keys)
# - BASE_URL, BASE_URL_OPTIONS: Base URL selection (assumed constant, uses DEFAULT_BASE_URL)
# - CONFIG_DATA, CONFIG_LOADED_PATH, LAST_SAVED_YAML: Config data (now uses @st.cache_data)
# - SELECTED_JOB, JOBS_CACHE, RECOMMEND_JOB_SYNCED: Job data (now uses @st.cache_data + minimal index)
# - ANALYSIS_NOTES: User notes for analysis (not used in analysis API, removed from UI)
#
class SessionKeys:
    # ============================================================================
    # CORE APPLICATION STATE
    # ============================================================================
    
    
    # Configuration management
    CRITERIA_PATH = "criteria_path"         # Path to jobs.yaml configuration file
    
    # Job selection (minimal state)
    SELECTED_JOB_INDEX = "selected_job_index"  # Index of selected job (only index needed)
    
    
    # ============================================================================
    # RESUME & GREETING MANAGEMENT
    # ============================================================================
    
    # Resume caching (performance optimization)
    CACHED_ONLINE_RESUME = "cached_online_resume"  # Cached online resume text for current candidate
    
    
    # ============================================================================
    # ANALYSIS & MESSAGING
    # ============================================================================
    
    # AI analysis functionality
    ANALYSIS_RESULTS = "analysis_results"   # AI analysis results (skill, startup_fit, etc.)
    
    # Message generation
    GENERATED_MESSAGES = "generated_messages"  # Generated message drafts by chat_id


def ensure_state() -> None:
    """Initialise shared Streamlit session state values once."""
    if SessionKeys.CRITERIA_PATH not in st.session_state:
        candidate = DEFAULT_CRITERIA_PATH.resolve()
        st.session_state[SessionKeys.CRITERIA_PATH] = str(candidate)


def discover_config_paths() -> List[Path]:
    """Return possible YAML config paths under the working directory."""
    root = Path.cwd()
    search_dirs: Iterable[Path] = [root / "config", root]
    seen: set[str] = set()
    results: List[Path] = []

    def add_path(path: Path) -> None:
        resolved = path.resolve()
        key = str(resolved)
        if resolved.is_file() and resolved.suffix in {".yaml", ".yml"} and key not in seen:
            seen.add(key)
            results.append(resolved)

    for directory in search_dirs:
        if directory.exists() and directory.is_dir():
            for file in sorted(directory.glob("*.ya?ml")):
                add_path(file)

    default_resolved = DEFAULT_CRITERIA_PATH.resolve()
    if str(default_resolved) not in seen and default_resolved.exists():
        results.insert(0, default_resolved)

    if not results:
        results.append(default_resolved)

    return results


@st.cache_data(ttl=60, show_spinner="加载岗位配置中...")
def load_jobs_from_path(path: Path) -> List[Dict[str, Any]]:
    """Load jobs from YAML file with caching."""
    try:
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("roles"), list):
            return data["roles"]
    except Exception as exc:
        st.warning(f"加载岗位配置失败: {exc}")
    return []


@st.cache_data(ttl=60, show_spinner="加载岗位配置中...")
def load_jobs() -> List[Dict[str, Any]]:
    """Load jobs from current config path with caching."""
    path = get_config_path()
    return load_jobs_from_path(path)


def get_selected_job(job_index: int = 0) -> Dict[str, Any]:
    """Get selected job by index with caching."""
    jobs = load_jobs()
    if not jobs or job_index >= len(jobs):
        return {}
    return jobs[job_index]


def sidebar_controls(*, include_config_path: bool = False, include_job_selector: bool = False) -> None:
    """Render common sidebar inputs with dropdown controls."""
    ensure_state()
    st.sidebar.header("全局设置")
    
    # Theme toggle
    st.sidebar.subheader("🎨 主题设置")
    theme_mode = st.sidebar.selectbox(
        "主题模式",
        options=["自动", "浅色", "深色"],
        index=0,
        help="自动模式会根据系统设置切换主题"
    )
    
    if theme_mode == "浅色":
        st.sidebar.markdown("""
        <style>
        .stApp {
            color-scheme: light;
        }
        </style>
        """, unsafe_allow_html=True)
    elif theme_mode == "深色":
        st.sidebar.markdown("""
        <style>
        .stApp {
            color-scheme: dark;
        }
        </style>
        """, unsafe_allow_html=True)
    # Auto mode uses system preference (default)


    config_path = Path(st.session_state[SessionKeys.CRITERIA_PATH]).resolve()

    if include_config_path:
        config_options = discover_config_paths()
        if config_path not in config_options:
            config_options.append(config_path)

        selected_config = st.sidebar.selectbox(
            "画像配置文件",
            config_options,
            index=config_options.index(config_path) if config_path in config_options else 0,
            format_func=lambda p: p.name,
        )
        config_path = selected_config.resolve()
        st.session_state[SessionKeys.CRITERIA_PATH] = str(config_path)
        # Clear job cache when config path changes
        load_jobs.clear()
    
    # Job selector
    if include_job_selector:
        roles = load_jobs()
        
        if roles:
            job_options = [f"{role.get('position', role.get('id', f'岗位{i+1}'))}" for i, role in enumerate(roles)]
            
            # Get current selection or default to 0
            current_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
            if current_idx >= len(roles):
                current_idx = 0
            
            selected_idx = st.sidebar.selectbox(
                "当前岗位",
                options=list(range(len(roles))),
                format_func=lambda idx: job_options[idx],
                index=current_idx,
            )
            
            # Store only the index, job data is loaded on demand
            st.session_state[SessionKeys.SELECTED_JOB_INDEX] = selected_idx
        else:
            st.sidebar.warning("⚠️ 未配置岗位，请到「岗位画像」页面添加")
            st.session_state[SessionKeys.SELECTED_JOB_INDEX] = 0


def get_config_path() -> Path:
    ensure_state()
    return Path(st.session_state[SessionKeys.CRITERIA_PATH]).expanduser().resolve()


@st.cache_data(ttl=60, show_spinner="加载配置中...")
def load_config(path: Path) -> Dict[str, Any]:
    """Load configuration from YAML file with caching."""
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        st.error(f"解析 YAML 失败: {exc}")
        return {}


def _dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_config(path: Path, data: Dict[str, Any], *, auto: bool = False) -> bool:
    yaml_text = _dump_yaml(data)
    if path.exists() and path.read_text(encoding="utf-8") == yaml_text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    # Clear cache to force reload on next access
    load_config.clear()
    if not auto:
        st.toast("配置已保存", icon="💾")
    return True


def auto_save_config(data: Dict[str, Any]) -> None:
    path = get_config_path()
    changed = write_config(path, data, auto=True)
    if changed:
        st.toast("配置已自动保存", icon="💾")


def get_config_data() -> Tuple[Dict[str, Any], Path]:
    """Get configuration data and path using cached loading."""
    path = get_config_path()
    config = load_config(path)
    return config, path


def refresh_config() -> None:
    """Refresh configuration cache."""
    load_config.clear()

@st.spinner("正在请求 API...")
def call_api(method: str, path: str, **kwargs) -> Tuple[bool, Any]:
    """Make HTTP request to boss_service API.
    
    Uses constant base URL from DEFAULT_BASE_URL.
    
    Note: Spinner should be used by callers with: with st.spinner("..."):
    """
    url = DEFAULT_BASE_URL.rstrip("/") + path
    try:
        response = requests.request(method.upper(), url, timeout=30, **kwargs)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return True, response.json()
    except requests.RequestException as exc:
        return False, str(exc)
    except json.JSONDecodeError:
        return False, "响应不是有效的 JSON"


def ensure_list(container: Dict[str, Any], key: str) -> list:
    value = container.get(key)
    if not isinstance(value, list):
        value = [] if value in (None, "") else [value]
        container[key] = value
    return value


def ensure_dict(container: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        value = {} if value in (None, "") else {"value": value}
        container[key] = value
    return value
