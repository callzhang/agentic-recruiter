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


def ensure_state() -> None:
    """Initialise shared Streamlit session state values once."""
    if "base_url" not in st.session_state:
        st.session_state["base_url"] = DEFAULT_BASE_URL
    if "base_url_options" not in st.session_state:
        st.session_state["base_url_options"] = [DEFAULT_BASE_URL]
    if "criteria_path" not in st.session_state:
        candidate = DEFAULT_CRITERIA_PATH.resolve()
        st.session_state["criteria_path"] = str(candidate)
    if "_last_saved_yaml" not in st.session_state:
        st.session_state["_last_saved_yaml"] = None
    if "selected_job" not in st.session_state:
        st.session_state["selected_job"] = None
    if "_jobs_cache" not in st.session_state:
        st.session_state["_jobs_cache"] = []


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
    base_options = _options_with_current(st.session_state["base_url_options"], st.session_state["base_url"])
    st.session_state["base_url_options"] = base_options
    selected_base = st.sidebar.selectbox(
        "API 服务地址",
        base_options,
        index=base_options.index(st.session_state["base_url"]),
        key="__base_url_select__",
    )
    st.session_state["base_url"] = selected_base

    new_base = st.sidebar.text_input("新增 API 地址", key="__base_url_new__", placeholder="http://127.0.0.1:5001")
    if st.sidebar.button("添加 API 地址", key="__base_url_add_btn__"):
        if new_base and new_base not in base_options:
            base_options.append(new_base)
            st.session_state["base_url_options"] = base_options
            st.session_state["base_url"] = new_base
            st.sidebar.success("已添加新的 API 地址")
        st.session_state["__base_url_new__"] = ""

    config_path = Path(st.session_state["criteria_path"]).resolve()

    if include_config_path:
        config_options = discover_config_paths()
        if config_path not in config_options:
            config_options.append(config_path)

        selected_config = st.sidebar.selectbox(
            "画像配置文件",
            config_options,
            index=config_options.index(config_path) if config_path in config_options else 0,
            format_func=lambda p: p.name,
            key="__config_path_select__",
        )
        config_path = selected_config.resolve()
        st.session_state["criteria_path"] = str(config_path)
        st.session_state.pop("_jobs_cache", None)
    
    # Job selector
    if include_job_selector:
        config = load_config(get_config_path())
        roles = config.get("roles", [])
        
        # Update jobs cache
        st.session_state["_jobs_cache"] = roles
        
        if roles:
            # Get current selection or default to 0
            current_idx = st.session_state.get("selected_job_index", 0)
            if current_idx >= len(roles):
                current_idx = 0
            
            job_options = [f"{role.get('position', role.get('id', f'岗位{i+1}'))}" for i, role in enumerate(roles)]
            
            selected_idx = st.sidebar.selectbox(
                "当前岗位",
                options=list(range(len(roles))),
                format_func=lambda idx: job_options[idx],
                index=current_idx,
                key="__job_selector__",
            )
            
            # Update session state with both index and job object
            st.session_state["selected_job_index"] = selected_idx
            st.session_state["selected_job"] = roles[selected_idx]
        else:
            st.sidebar.warning("⚠️ 未配置岗位，请到「岗位画像」页面添加")
            st.session_state["selected_job"] = None
            st.session_state["selected_job_index"] = 0


def get_config_path() -> Path:
    ensure_state()
    return Path(st.session_state["criteria_path"]).expanduser().resolve()


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
    last_yaml = st.session_state.get("_last_saved_yaml")
    if last_yaml == yaml_text and path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    st.session_state["_last_saved_yaml"] = yaml_text
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
    cache_key = "_config_loaded_path"
    if (
        "config_data" not in st.session_state
        or st.session_state.get(cache_key) != str(path)
    ):
        config = load_config(path)
        st.session_state["config_data"] = config
        st.session_state[cache_key] = str(path)
        st.session_state["_last_saved_yaml"] = _dump_yaml(config)
    return st.session_state["config_data"], path


def refresh_config() -> None:
    path = get_config_path()
    config = load_config(path)
    st.session_state["config_data"] = config
    st.session_state["_config_loaded_path"] = str(path)
    st.session_state["_last_saved_yaml"] = _dump_yaml(config)


def call_api(base_url: str, method: str, path: str, **kwargs) -> Tuple[bool, Any]:
    """Make HTTP request to boss_service API.
    
    Note: Spinner should be used by callers with: with st.spinner("..."):
    """
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
