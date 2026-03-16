from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Any

import yaml

from venv_utils import VENV_HOME, get_venv_by_name, plain_relative


ROOT = Path(__file__).resolve().parent.parent
HIDDEN_ENV_DIR = ROOT / ".envs"
HIDDEN_CONFIG_HOME = HIDDEN_ENV_DIR / "configs"
HIDDEN_SLURM_HOME = HIDDEN_ENV_DIR / "slurm"
BACKUP_HOME = HIDDEN_ENV_DIR / "backups"
ACTIVE_CONFIG_DIR = ROOT / "configs"
ACTIVE_SLURM_DIR = ROOT / "slurm"

INTERACTIVE_MODE = "interactive"
NON_INTERACTIVE_MODE = "non-interactive"
ENV_MODE_ALIASES = {
    "interactive": INTERACTIVE_MODE,
    "local": INTERACTIVE_MODE,
    "non-interactive": NON_INTERACTIVE_MODE,
    "non_interactive": NON_INTERACTIVE_MODE,
    "noninteractive": NON_INTERACTIVE_MODE,
    "batch": NON_INTERACTIVE_MODE,
    "slurm": NON_INTERACTIVE_MODE,
}

DEFAULT_TRAIN_CONFIG = "train_example.yaml"
DEFAULT_ENV_CONFIG = "environment.yaml"
DEFAULT_SLURM_CONFIG = "slurm_job.yaml"
DEFAULT_SLURM_SCRIPT = "submit.sh"
DEFAULT_OUTPUTS_DIR = "outputs2"


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_env_state() -> dict[str, Any]:
    return {
        "mode": None,
        "venv_name": None,
        "updated_at": None,
    }


def normalize_env_mode(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    cleaned = raw_value.strip().lower().replace("_", "-")
    if not cleaned:
        return None
    if cleaned not in ENV_MODE_ALIASES:
        known = ", ".join(sorted(ENV_MODE_ALIASES))
        raise ValueError(f"Unknown env mode '{raw_value}'. Known modes: {known}")
    return ENV_MODE_ALIASES[cleaned]


def mode_storage_name(mode: str) -> str:
    normalized = normalize_env_mode(mode)
    if normalized is None:
        raise ValueError("Env mode is not set.")
    return normalized.replace("-", "_")


def ensure_hidden_roots() -> None:
    HIDDEN_ENV_DIR.mkdir(parents=True, exist_ok=True)
    HIDDEN_CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    HIDDEN_SLURM_HOME.mkdir(parents=True, exist_ok=True)
    BACKUP_HOME.mkdir(parents=True, exist_ok=True)


def hidden_config_dir(user_id: str, mode: str) -> Path:
    return HIDDEN_CONFIG_HOME / user_id / mode_storage_name(mode)


def hidden_slurm_dir(user_id: str, mode: str) -> Path:
    return HIDDEN_SLURM_HOME / user_id / mode_storage_name(mode)


def backup_existing_root_path(path: Path) -> Path:
    ensure_hidden_roots()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = BACKUP_HOME / f"{path.name}_{timestamp}"
    suffix = 2
    while candidate.exists():
        candidate = BACKUP_HOME / f"{path.name}_{timestamp}_{suffix}"
        suffix += 1
    shutil.move(str(path), str(candidate))
    return candidate


def clear_generated_directory(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.exists():
        shutil.rmtree(path)


def link_active_directory(link_path: Path, target_dir: Path) -> None:
    ensure_hidden_roots()
    target_dir.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.exists():
        backup_existing_root_path(link_path)
    os.symlink(target_dir, link_path, target_is_directory=True)


def hide_active_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if path.exists():
        backup_existing_root_path(path)


def venv_details(venv_name: str | None) -> dict[str, Any]:
    if not venv_name:
        return {
            "name": None,
            "path": None,
            "relative_path": None,
            "exists": False,
        }

    try:
        info = get_venv_by_name(venv_name)
        venv_path = info.path
        resolved_name = info.name
    except Exception:
        venv_path = VENV_HOME / venv_name
        resolved_name = venv_name

    return {
        "name": resolved_name,
        "path": str(venv_path),
        "relative_path": plain_relative(venv_path),
        "exists": venv_path.exists(),
    }


def training_payload(username: str, mode: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "user": username,
        "mode": mode,
        "generated_at": current_timestamp(),
        "train": deepcopy(snapshot),
    }


def environment_payload(username: str, mode: str, env_state: dict[str, Any]) -> dict[str, Any]:
    venv_info = venv_details(env_state.get("venv_name"))
    return {
        "user": username,
        "mode": mode,
        "generated_at": current_timestamp(),
        "venv": {
            "name": venv_info["name"],
            "path": venv_info["relative_path"],
            "exists": venv_info["exists"],
        },
        "active_files": {
            "train_config": f"configs/{DEFAULT_TRAIN_CONFIG}",
            "slurm_config": f"configs/{DEFAULT_SLURM_CONFIG}" if mode == NON_INTERACTIVE_MODE else None,
            "slurm_script": f"slurm/{DEFAULT_SLURM_SCRIPT}" if mode == NON_INTERACTIVE_MODE else None,
        },
    }


def slurm_job_payload(username: str, env_state: dict[str, Any]) -> dict[str, Any]:
    venv_info = venv_details(env_state.get("venv_name"))
    return {
        "job_name": "ntrno_train",
        "account": "your_account",
        "nodes": 1,
        "ntasks_per_node": 1,
        "partition": "your_partition",
        "qos": "your_qos",
        "cpus_per_task": 8,
        "gpus": 1,
        "mem": "32G",
        "time": "02:00:00",
        "user": username,
        "venv_name": venv_info["name"],
        "venv_path": venv_info["relative_path"],
        "train_config": f"configs/{DEFAULT_TRAIN_CONFIG}",
        "outputs_dir": DEFAULT_OUTPUTS_DIR,
        "srcpath": str(ROOT),
    }


def slurm_script_text(env_state: dict[str, Any]) -> str:
    venv_info = venv_details(env_state.get("venv_name"))
    selected_venv = venv_info["path"] or ""
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f'SELECTED_VENV="{selected_venv}"',
        "",
        'if [ -z "${VENV:-}" ] && [ -n "${SELECTED_VENV}" ]; then',
        '    VENV="${SELECTED_VENV}"',
        "fi",
        "",
        'if [ -z "${VENV:-}" ]; then',
        "    echo \"Error: VENV is not set. Run via 'make slurm'.\" >&2",
        "    exit 1",
        "fi",
        "",
        'source "${VENV}/bin/activate"',
        "",
        'if [ -z "${SRCPATH:-}" ]; then',
        '    echo "Error: SRCPATH is not set." >&2',
        "    exit 1",
        "fi",
        "",
        'export PYTHONPATH="${PYTHONPATH:-${SRCPATH}}"',
        "",
        f'TRAIN_CONFIG="${{TRAIN_CONFIG:-configs/{DEFAULT_TRAIN_CONFIG}}}"',
        f'OUTPUTS_DIR="${{OUTPUTS_DIR:-{DEFAULT_OUTPUTS_DIR}}}"',
        "",
        'echo "Using TRAIN_CONFIG=${TRAIN_CONFIG}"',
        'echo "Writing artifacts to ${OUTPUTS_DIR}"',
    ]
    return "\n".join(lines) + "\n"


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def refresh_user_mode_assets(
    user_id: str,
    username: str,
    snapshot: dict[str, Any],
    env_state: dict[str, Any] | None,
) -> None:
    ensure_hidden_roots()
    merged_state = default_env_state()
    if env_state:
        merged_state.update(env_state)

    for mode in (INTERACTIVE_MODE, NON_INTERACTIVE_MODE):
        config_dir = hidden_config_dir(user_id, mode)
        clear_generated_directory(config_dir)
        write_yaml(config_dir / DEFAULT_TRAIN_CONFIG, training_payload(username, mode, snapshot))
        write_yaml(config_dir / DEFAULT_ENV_CONFIG, environment_payload(username, mode, merged_state))
        if mode == NON_INTERACTIVE_MODE:
            write_yaml(config_dir / DEFAULT_SLURM_CONFIG, slurm_job_payload(username, merged_state))

    interactive_slurm = hidden_slurm_dir(user_id, INTERACTIVE_MODE)
    remove_path(interactive_slurm)

    non_interactive_slurm = hidden_slurm_dir(user_id, NON_INTERACTIVE_MODE)
    clear_generated_directory(non_interactive_slurm)
    script_path = non_interactive_slurm / DEFAULT_SLURM_SCRIPT
    write_text(script_path, slurm_script_text(merged_state))
    script_path.chmod(0o755)


def deactivate_active_workspace() -> None:
    hide_active_path(ACTIVE_CONFIG_DIR)
    hide_active_path(ACTIVE_SLURM_DIR)


def activate_user_mode_workspace(user_id: str, env_state: dict[str, Any] | None) -> None:
    merged_state = default_env_state()
    if env_state:
        merged_state.update(env_state)

    mode = normalize_env_mode(merged_state.get("mode"))
    if mode is None:
        deactivate_active_workspace()
        return

    link_active_directory(ACTIVE_CONFIG_DIR, hidden_config_dir(user_id, mode))
    if mode == NON_INTERACTIVE_MODE:
        link_active_directory(ACTIVE_SLURM_DIR, hidden_slurm_dir(user_id, mode))
    else:
        hide_active_path(ACTIVE_SLURM_DIR)


def remove_user_mode_assets(user_id: str) -> None:
    remove_path(HIDDEN_CONFIG_HOME / user_id)
    remove_path(HIDDEN_SLURM_HOME / user_id)


def describe_env_workspace(user_id: str, username: str, env_state: dict[str, Any] | None) -> dict[str, Any]:
    merged_state = default_env_state()
    if env_state:
        merged_state.update(env_state)

    mode = normalize_env_mode(merged_state.get("mode"))
    venv_info = venv_details(merged_state.get("venv_name"))
    config_dir = hidden_config_dir(user_id, mode) if mode is not None else None
    slurm_dir = hidden_slurm_dir(user_id, mode) if mode == NON_INTERACTIVE_MODE else None
    return {
        "user": username,
        "mode": mode,
        "venv": venv_info,
        "hidden_configs": plain_relative(config_dir) if config_dir is not None else None,
        "hidden_slurm": plain_relative(slurm_dir) if slurm_dir is not None else None,
        "active_configs": plain_relative(ACTIVE_CONFIG_DIR) if ACTIVE_CONFIG_DIR.exists() or ACTIVE_CONFIG_DIR.is_symlink() else None,
        "active_slurm": plain_relative(ACTIVE_SLURM_DIR) if ACTIVE_SLURM_DIR.exists() or ACTIVE_SLURM_DIR.is_symlink() else None,
    }
