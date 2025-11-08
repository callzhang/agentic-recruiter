#!/bin/bash
# Single-file macOS installer wrapper for HR teammates.
# Double-click this .command file to run the full bootstrap flow.

set -euo pipefail

if [ -n "${BOSSZP_PYTHON:-}" ]; then
  PYTHON_BIN="$BOSSZP_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "[!] Python 3.11+ is required but was not found on this system."
  echo "    Please install Python from https://www.python.org/downloads/macos/ and retry."
  exit 1
fi

echo "[*] Launching Boss HR installer with ${PYTHON_BIN}"
exec "$PYTHON_BIN" - "$@" <<'PY'
from __future__ import annotations

import argparse
import getpass
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_URL = "https://github.com/callzhang/recruiter.git"
DEFAULT_DIR_NAME = "bosszhipin_bot"
VENV_NAME = ".venv_hr"


class BootstrapError(Exception):
    """Fatal error raised during the bootstrap process."""


@dataclass
class PromptField:
    key: str
    label: str
    default: Any = ""
    required: bool = True
    secret: bool = False
    value_type: type = str
    allow_blank: bool = False

    def format_default(self) -> str:
        if self.default is None:
            return ""
        if isinstance(self.default, bool):
            return "yes" if self.default else "no"
        return str(self.default)


ENV_FIELDS: Tuple[PromptField, ...] = (
    PromptField(
        key="OPENAI_API_KEY",
        label="OpenAI API key",
        default="",
        required=True,
        secret=True,
    ),
    PromptField(
        key="OPENAI_BASE_URL",
        label="OpenAI API base URL",
        default="https://api.openai.com/v1",
    ),
    PromptField(
        key="LANGSMITH_API_KEY",
        label="LangSmith API key (optional)",
        default="",
        required=False,
        secret=True,
        allow_blank=True,
    ),
    PromptField(
        key="DINGTALK_WEBHOOK",
        label="DingTalk webhook (optional)",
        default="",
        required=False,
        allow_blank=True,
    ),
    PromptField(
        key="__VERSION__",
        label="Version label",
        default="2.2.0",
    ),
)

SECRETS_SECTIONS: Tuple[Tuple[str, Tuple[PromptField, ...]], ...] = (
    (
        "zilliz",
        (
            PromptField("endpoint", "Zilliz endpoint URL", "https://", True),
            PromptField("user", "Zilliz username", "", True),
            PromptField("password", "Zilliz password", "", True, secret=True),
            PromptField(
                "collection_name",
                "Zilliz collection name",
                "CN_candidates",
            ),
            PromptField(
                "embedding_model",
                "Zilliz embedding model",
                "text-embedding-3-small",
            ),
            PromptField(
                "embedding_dim",
                "Embedding dimension",
                1536,
                value_type=int,
            ),
            PromptField(
                "similarity_top_k",
                "Similarity top_k",
                5,
                value_type=int,
            ),
            PromptField(
                "enable_cache",
                "Enable vector cache (yes/no)",
                False,
                value_type=bool,
            ),
        ),
    ),
    (
        "zilliz_recruiter_agent",
        (
            PromptField("endpoint", "Recruiter agent Zilliz endpoint", "https://", True),
            PromptField("user", "Recruiter agent username", "", True),
            PromptField("password", "Recruiter agent password", "", True, secret=True),
            PromptField(
                "collection_name",
                "Recruiter agent collection name",
                "CN_recruiter_agent",
            ),
            PromptField(
                "embedding_model",
                "Recruiter agent embedding model",
                "text-embedding-3-small",
            ),
            PromptField(
                "embedding_dim",
                "Recruiter agent embedding dim",
                1536,
                value_type=int,
            ),
            PromptField(
                "similarity_top_k",
                "Recruiter agent similarity top_k",
                5,
                value_type=int,
            ),
            PromptField(
                "enable_cache",
                "Recruiter agent cache (yes/no)",
                False,
                value_type=bool,
            ),
        ),
    ),
    (
        "openai",
        (
            PromptField("api_key", "OpenAI API key", "", True, secret=True),
            PromptField("name", "OpenAI bot name", "CN_recruiting_bot"),
        ),
    ),
    (
        "dingtalk",
        (
            PromptField("url", "DingTalk webhook URL", "", False, allow_blank=True),
            PromptField("secret", "DingTalk secret", "", False, secret=True, allow_blank=True),
        ),
    ),
    (
        "sentry",
        (
            PromptField("dsn", "Sentry DSN", "", False, allow_blank=True),
            PromptField("environment", "Sentry environment", "development", False),
            PromptField("release", "Sentry release tag", "2.2.0", False),
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clone/update the Boss直聘 automation repo for HR teammates."
    )
    parser.add_argument(
        "--install-dir",
        help="Target directory for the repository (defaults to ~/bosszhipin_bot)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip prompts and stick to defaults/env vars.",
    )
    return parser.parse_args()


def print_banner() -> None:
    line = "=" * 72
    print(line)
    print(" Boss直聘自动化机器人 - HR 安装助手 ")
    print(line)
    print("This script will clone/update the repo and start the local service.")
    print()


def ensure_python_version() -> None:
    if sys.version_info < (3, 11):
        raise BootstrapError(
            "Python 3.11+ is required. Please install a newer Python interpreter."
        )


def ensure_git_installed() -> None:
    if shutil.which("git"):
        return
    raise BootstrapError(
        "Git is not installed or not on PATH. Please install Git first."
    )


def choose_install_directory(
    requested_path: str | None, non_interactive: bool
) -> Path:
    default_path = Path(requested_path or (Path.home() / DEFAULT_DIR_NAME)).expanduser()
    if non_interactive:
        print(f"[+] Using install directory: {default_path}")
        return default_path

    print(f"Default install directory: {default_path}")
    user_input = input("Press Enter to accept or type a different path: ").strip()
    target = Path(user_input) if user_input else default_path
    target = target.expanduser()
    print(f"[+] Repository will live at: {target}")
    return target


def run_command(
    cmd: List[str], *, cwd: Path | None = None, env: Dict[str, str] | None = None
) -> None:
    pretty = shlex.join(cmd)
    location = f" (cwd={cwd})" if cwd else ""
    print(f"    $ {pretty}{location}")
    try:
        subprocess.run(cmd, cwd=cwd, env=env, check=True)
    except FileNotFoundError as exc:
        raise BootstrapError(f"Command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise BootstrapError(f"Command failed: {pretty}") from exc


def ensure_repository(target_dir: Path) -> Path:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    git_dir = target_dir / ".git"

    if target_dir.exists():
        if not git_dir.exists():
            raise BootstrapError(
                f"{target_dir} already exists but is not a git repository."
            )
        print("[*] Repository detected, pulling latest changes...")
        run_command(["git", "fetch", "--all"], cwd=target_dir)
        run_command(["git", "pull", "--ff-only"], cwd=target_dir)
    else:
        print("[*] Cloning repository...")
        run_command(["git", "clone", REPO_URL, str(target_dir)])
    return target_dir


def is_interactive(non_interactive_flag: bool) -> bool:
    return sys.stdin.isatty() and not non_interactive_flag


def prompt_value(
    field: PromptField,
    *,
    interactive: bool,
) -> Any:
    default_text = field.format_default()
    if not interactive:
        return field.default

    while True:
        prompt = field.label
        if default_text:
            prompt += f" [{default_text}]"
        prompt += ": "
        try:
            raw = (
                getpass.getpass(prompt)
                if field.secret
                else input(prompt)
            )
        except EOFError:
            raw = ""
        raw = raw.strip()
        if raw:
            return coerce_value(raw, field)
        if field.default not in (None, ""):
            return field.default
        if not field.required or field.allow_blank:
            return "" if field.value_type is str else field.default
        print("Value required. Please try again.")


def coerce_value(value: str, field: PromptField) -> Any:
    if field.value_type is bool:
        return str_to_bool(value)
    if field.value_type is int:
        try:
            return int(value)
        except ValueError as exc:
            raise BootstrapError(f"Expected a number for {field.label}") from exc
    return value


def str_to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"y", "yes", "true", "1"}:
        return True
    if lowered in {"n", "no", "false", "0"}:
        return False
    raise BootstrapError(f"Could not interpret '{value}' as a boolean.")


def collect_env_data(interactive: bool) -> Dict[str, Any]:
    print("[*] Creating .env (press Enter to accept defaults)...")
    values: Dict[str, Any] = {}
    for field in ENV_FIELDS:
        values[field.key] = prompt_value(field, interactive=interactive)
    return values


def write_env_file(env_path: Path, values: Dict[str, Any]) -> None:
    lines = [
        "# Auto-generated by install_hr.command",
        "# Update values here if credentials rotate.",
        "",
    ]
    for key, value in values.items():
        lines.append(f"{key} = {value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[+] Wrote {env_path}")


def collect_secrets_data(interactive: bool) -> Dict[str, Dict[str, Any]]:
    print("[*] Creating config/secrets.yaml (press Enter to accept defaults)...")
    secrets: Dict[str, Dict[str, Any]] = {}
    for section, fields in SECRETS_SECTIONS:
        print(f"  - {section}")
        section_values: Dict[str, Any] = {}
        for field in fields:
            section_values[field.key] = prompt_value(field, interactive=interactive)
        secrets[section] = section_values
    return secrets


def dump_yaml(data: Dict[str, Any], indent: int = 0) -> List[str]:
    lines: List[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(dump_yaml(value, indent + 2))
        else:
            lines.append(f"{pad}{key}: {format_scalar(value)}")
    return lines


def format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def ensure_env_files(repo_dir: Path, *, interactive: bool) -> None:
    env_path = repo_dir / ".env"
    secrets_path = repo_dir / "config" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)

    if env_path.exists():
        print(f"[=] {env_path} already exists. Skipping creation.")
    else:
        values = collect_env_data(interactive)
        write_env_file(env_path, values)

    if secrets_path.exists():
        print(f"[=] {secrets_path} already exists. Skipping creation.")
    else:
        secrets = collect_secrets_data(interactive)
        contents = [
            "# Auto-generated by install_hr.command",
            "# Update credentials here if they change.",
            "",
        ]
        contents.extend(dump_yaml(secrets))
        secrets_path.write_text("\n".join(contents) + "\n", encoding="utf-8")
        print(f"[+] Wrote {secrets_path}")


def ensure_virtualenv(repo_dir: Path) -> Path:
    venv_dir = repo_dir / VENV_NAME
    python_executable = (
        venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
    )
    if not venv_dir.exists():
        print("[*] Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        print("[=] Reusing existing virtual environment.")

    print("[*] Installing Python dependencies...")
    run_command([str(python_executable), "-m", "pip", "install", "--upgrade", "pip"])
    run_command(
        [str(python_executable), "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=repo_dir,
    )
    print("[*] Ensuring Playwright Chromium is installed...")
    run_command(
        [str(python_executable), "-m", "playwright", "install", "chromium"],
        cwd=repo_dir,
    )
    return python_executable


def load_dotenv(env_path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip("'\"")
    return values


def start_service(python_executable: Path, repo_dir: Path) -> None:
    env = os.environ.copy()
    env.update(load_dotenv(repo_dir / ".env"))
    env["PYTHONUNBUFFERED"] = "1"
    start_script = repo_dir / "start_service.py"
    if not start_script.exists():
        raise BootstrapError(f"{start_script} not found.")

    print("[*] Starting Boss service (Ctrl+C to stop)...")
    process = subprocess.Popen(
        [str(python_executable), str(start_script)],
        cwd=repo_dir,
        env=env,
    )
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n[!] Stopping service...")
        process.terminate()
        process.wait()


def main() -> None:
    args = parse_args()
    non_interactive = (
        args.non_interactive
        or os.environ.get("BOSSZP_NON_INTERACTIVE", "").lower() == "true"
        or not sys.stdin.isatty()
    )

    print_banner()
    ensure_python_version()
    ensure_git_installed()
    repo_dir = ensure_repository(
        choose_install_directory(args.install_dir, non_interactive)
    )
    ensure_env_files(repo_dir, interactive=is_interactive(non_interactive))
    python_executable = ensure_virtualenv(repo_dir)
    start_service(python_executable, repo_dir)


if __name__ == "__main__":
    try:
        main()
    except BootstrapError as exc:
        print(f"[!] {exc}")
        sys.exit(1)
PY
