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
class SessionKeys:
    # Core application state
    BASE_URL = "base_url"
    BASE_URL_OPTIONS = "base_url_options"
    CRITERIA_PATH = "criteria_path"
    CONFIG_DATA = "config_data"
    CONFIG_LOADED_PATH = "_config_loaded_path"
    LAST_SAVED_YAML = "_last_saved_yaml"
    
    # Job management
    SELECTED_JOB = "selected_job"
    SELECTED_JOB_INDEX = "selected_job_index"
    JOBS_CACHE = "_jobs_cache"
    RECOMMEND_JOB_SYNCED = "_recommend_job_synced"
    
    # Resume and greeting management
    CACHED_ONLINE_RESUME = "cached_online_resume"
    RECOMMEND_GREET_MESSAGE = "recommend_greet_message"
    
    # Analysis and messaging
    ANALYSIS_NOTES = "analysis_notes"
    ANALYSIS_RESULTS = "analysis_results"
    GENERATED_MESSAGES = "generated_messages"
    
    # Page-specific state
    FIRST_ROLE_POSITION = "first_role_position"
    FIRST_ROLE_ID = "first_role_id"
    NEW_ROLE_POSITION = "new_role_position"
    NEW_ROLE_ID = "new_role_id"
    
    # UI control keys
    BASE_URL_SELECT = "__base_url_select__"
    BASE_URL_NEW = "__base_url_new__"
    BASE_URL_ADD_BTN = "__base_url_add_btn__"
    CONFIG_PATH_SELECT = "__config_path_select__"
    JOB_SELECTOR = "__job_selector__"


def ensure_state() -> None:
    """Initialise shared Streamlit session state values once."""
    if SessionKeys.BASE_URL not in st.session_state:
        st.session_state[SessionKeys.BASE_URL] = DEFAULT_BASE_URL
    if SessionKeys.BASE_URL_OPTIONS not in st.session_state:
        st.session_state[SessionKeys.BASE_URL_OPTIONS] = [DEFAULT_BASE_URL]
    if SessionKeys.CRITERIA_PATH not in st.session_state:
        candidate = DEFAULT_CRITERIA_PATH.resolve()
        st.session_state[SessionKeys.CRITERIA_PATH] = str(candidate)
    if SessionKeys.LAST_SAVED_YAML not in st.session_state:
        st.session_state[SessionKeys.LAST_SAVED_YAML] = None
    if SessionKeys.SELECTED_JOB not in st.session_state:
        st.session_state[SessionKeys.SELECTED_JOB] = None
    if SessionKeys.JOBS_CACHE not in st.session_state:
        st.session_state[SessionKeys.JOBS_CACHE] = []
    if SessionKeys.SELECTED_JOB_INDEX not in st.session_state:
        st.session_state[SessionKeys.SELECTED_JOB_INDEX] = 0
    if SessionKeys.RECOMMEND_JOB_SYNCED not in st.session_state:
        st.session_state[SessionKeys.RECOMMEND_JOB_SYNCED] = None


def _options_with_current(options: list[str], current: str) -> list[str]:
    if current and current not in options:
        options.append(current)
    return options


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


def load_jobs_from_path(path: Path) -> List[Dict[str, Any]]:
    try:
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("roles"), list):
            return data["roles"]
    except Exception as exc:
        st.warning(f"加载岗位配置失败: {exc}")
    return []


def sidebar_controls(*, include_config_path: bool = False, include_job_selector: bool = False) -> None:
    """Render common sidebar inputs with dropdown controls."""
    ensure_state()
    st.sidebar.header("全局设置")

    # Base URL selection
    base_options = _options_with_current(st.session_state[SessionKeys.BASE_URL_OPTIONS], st.session_state[SessionKeys.BASE_URL])
    st.session_state[SessionKeys.BASE_URL_OPTIONS] = base_options
    selected_base = st.sidebar.selectbox(
        "API 服务地址",
        base_options,
        index=base_options.index(st.session_state[SessionKeys.BASE_URL]),
        key=SessionKeys.BASE_URL_SELECT,
    )
    st.session_state[SessionKeys.BASE_URL] = selected_base

    new_base = st.sidebar.text_input("新增 API 地址", key=SessionKeys.BASE_URL_NEW, placeholder="http://127.0.0.1:5001")
    if st.sidebar.button("添加 API 地址", key=SessionKeys.BASE_URL_ADD_BTN):
        if new_base and new_base not in base_options:
            base_options.append(new_base)
            st.session_state[SessionKeys.BASE_URL_OPTIONS] = base_options
            st.session_state[SessionKeys.BASE_URL] = new_base
            st.sidebar.success("已添加新的 API 地址")
        st.session_state[SessionKeys.BASE_URL_NEW] = ""

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
            key=SessionKeys.CONFIG_PATH_SELECT,
        )
        config_path = selected_config.resolve()
        st.session_state[SessionKeys.CRITERIA_PATH] = str(config_path)
        st.session_state.pop(SessionKeys.JOBS_CACHE, None)
    
    # Job selector
    if include_job_selector:
        config = load_config(get_config_path())
        roles = config.get("roles", [])
        
        # Update jobs cache
        st.session_state[SessionKeys.JOBS_CACHE] = roles
        
        if roles:
            # Get current selection or default to 0
            current_idx = st.session_state.get(SessionKeys.SELECTED_JOB_INDEX, 0)
            if current_idx >= len(roles):
                current_idx = 0
            
            job_options = [f"{role.get('position', role.get('id', f'岗位{i+1}'))}" for i, role in enumerate(roles)]
            
            selected_idx = st.sidebar.selectbox(
                "当前岗位",
                options=list(range(len(roles))),
                format_func=lambda idx: job_options[idx],
                index=current_idx,
                key=SessionKeys.JOB_SELECTOR,
            )
            
            # Update session state with both index and job object
            st.session_state[SessionKeys.SELECTED_JOB_INDEX] = selected_idx
            st.session_state[SessionKeys.SELECTED_JOB] = roles[selected_idx]
        else:
            st.sidebar.warning("⚠️ 未配置岗位，请到「岗位画像」页面添加")
            st.session_state[SessionKeys.SELECTED_JOB] = None
            st.session_state[SessionKeys.SELECTED_JOB_INDEX] = 0


def get_config_path() -> Path:
    ensure_state()
    return Path(st.session_state[SessionKeys.CRITERIA_PATH]).expanduser().resolve()


def load_config(path: Path) -> Dict[str, Any]:
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
    last_yaml = st.session_state.get(SessionKeys.LAST_SAVED_YAML)
    if last_yaml == yaml_text and path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    st.session_state[SessionKeys.LAST_SAVED_YAML] = yaml_text
    if not auto:
        st.toast("配置已保存", icon="💾")
    return True


def auto_save_config(data: Dict[str, Any]) -> None:
    path = get_config_path()
    changed = write_config(path, data, auto=True)
    if changed:
        st.toast("配置已自动保存", icon="💾")


def get_config_data() -> Tuple[Dict[str, Any], Path]:
    path = get_config_path()
    cache_key = SessionKeys.CONFIG_LOADED_PATH
    if (
        SessionKeys.CONFIG_DATA not in st.session_state
        or st.session_state.get(cache_key) != str(path)
    ):
        config = load_config(path)
        st.session_state[SessionKeys.CONFIG_DATA] = config
        st.session_state[cache_key] = str(path)
        st.session_state[SessionKeys.LAST_SAVED_YAML] = _dump_yaml(config)
    return st.session_state[SessionKeys.CONFIG_DATA], path


def refresh_config() -> None:
    path = get_config_path()
    config = load_config(path)
    st.session_state[SessionKeys.CONFIG_DATA] = config
    st.session_state[SessionKeys.CONFIG_LOADED_PATH] = str(path)
    st.session_state[SessionKeys.LAST_SAVED_YAML] = _dump_yaml(config)

@st.spinner("正在请求 API...")
def call_api(method: str, path: str, **kwargs) -> Tuple[bool, Any]:
    """Make HTTP request to boss_service API.
    
    Automatically uses base_url from st.session_state[SessionKeys.BASE_URL].
    
    Note: Spinner should be used by callers with: with st.spinner("..."):
    """
    base_url = st.session_state.get(SessionKeys.BASE_URL, DEFAULT_BASE_URL)
    url = base_url.rstrip("/") + path
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
