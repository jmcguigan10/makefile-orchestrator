from __future__ import annotations

import argparse
from pathlib import Path
import sys

from config_utils import (
    configs_path,
    env_state_path,
    get_current_user,
    list_users,
    load_env_state,
    load_profile,
    load_session,
    load_store,
)
from env_mode_utils import (
    ACTIVE_CONFIG_DIR,
    ACTIVE_SLURM_DIR,
    DEFAULT_ENV_CONFIG,
    DEFAULT_SLURM_CONFIG,
    DEFAULT_SLURM_SCRIPT,
    DEFAULT_TRAIN_CONFIG,
    INTERACTIVE_MODE,
    NON_INTERACTIVE_MODE,
    hidden_config_dir,
    hidden_slurm_dir,
)
from venv_utils import MANAGED_VENV_DIR, get_venv_by_name


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Check whether the local orchestrator state is internally coherent.")


def resolved_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except Exception:
        return path


def add_missing_file_failure(failures: list[str], path: Path) -> None:
    failures.append(f"missing required file: {path}")


def check_expected_files(base_dir: Path, filenames: list[str], failures: list[str]) -> None:
    if not base_dir.exists():
        failures.append(f"missing required directory: {base_dir}")
        return
    for filename in filenames:
        if not (base_dir / filename).is_file():
            add_missing_file_failure(failures, base_dir / filename)


def check_active_link(link_path: Path, expected_target: Path, failures: list[str]) -> None:
    if not link_path.is_symlink():
        failures.append(f"expected {link_path} to be a symlink to {expected_target}")
        return
    if resolved_path(link_path) != expected_target.resolve():
        failures.append(f"{link_path} points to {resolved_path(link_path)}, expected {expected_target}")


def check_absent_path(path: Path, failures: list[str]) -> None:
    if path.exists() or path.is_symlink():
        failures.append(f"expected {path} to be hidden, but it is present")


def check_user_state(user_id: str, failures: list[str]) -> None:
    config_file = configs_path(user_id)
    if not config_file.exists():
        failures.append(f"missing config store for user '{user_id}': {config_file}")
        return
    try:
        load_store(user_id)
    except Exception as exc:
        failures.append(f"failed to load config store for user '{user_id}': {exc}")

    state_file = env_state_path(user_id)
    if state_file.exists():
        try:
            load_env_state(user_id)
        except Exception as exc:
            failures.append(f"failed to load env state for user '{user_id}': {exc}")


def check_selected_venv(user_id: str, failures: list[str]) -> str | None:
    env_state = load_env_state(user_id)
    mode = env_state.get("mode")
    venv_name = env_state.get("venv_name")
    if mode is not None and not venv_name:
        failures.append(f"user '{user_id}' has env-mode '{mode}' but no venv selected")
    if venv_name is not None:
        try:
            get_venv_by_name(str(venv_name))
        except Exception as exc:
            failures.append(f"user '{user_id}' references unknown venv '{venv_name}': {exc}")
    return mode


def check_user_assets(user_id: str, mode: str | None, failures: list[str]) -> None:
    if mode is None:
        return

    interactive_config_dir = hidden_config_dir(user_id, INTERACTIVE_MODE)
    check_expected_files(
        interactive_config_dir,
        [DEFAULT_TRAIN_CONFIG, DEFAULT_ENV_CONFIG],
        failures,
    )

    if mode == NON_INTERACTIVE_MODE:
        noninteractive_config_dir = hidden_config_dir(user_id, NON_INTERACTIVE_MODE)
        noninteractive_slurm_dir = hidden_slurm_dir(user_id, NON_INTERACTIVE_MODE)
        check_expected_files(
            noninteractive_config_dir,
            [DEFAULT_TRAIN_CONFIG, DEFAULT_ENV_CONFIG, DEFAULT_SLURM_CONFIG],
            failures,
        )
        check_expected_files(
            noninteractive_slurm_dir,
            [DEFAULT_SLURM_SCRIPT],
            failures,
        )


def check_active_workspace(user_id: str, mode: str | None, failures: list[str]) -> None:
    if mode is None:
        check_absent_path(ACTIVE_CONFIG_DIR, failures)
        check_absent_path(ACTIVE_SLURM_DIR, failures)
        return

    expected_config_dir = hidden_config_dir(user_id, mode)
    check_active_link(ACTIVE_CONFIG_DIR, expected_config_dir, failures)

    if mode == NON_INTERACTIVE_MODE:
        expected_slurm_dir = hidden_slurm_dir(user_id, mode)
        check_active_link(ACTIVE_SLURM_DIR, expected_slurm_dir, failures)
    else:
        check_absent_path(ACTIVE_SLURM_DIR, failures)


def main() -> int:
    parser = build_parser()
    parser.parse_args()

    failures: list[str] = []
    warnings: list[str] = []

    try:
        session = load_session()
    except Exception as exc:
        print(f"doctor failed: could not load session state: {exc}", file=sys.stderr)
        return 1

    if not MANAGED_VENV_DIR.exists():
        failures.append(f"managed venv is missing: {MANAGED_VENV_DIR}")

    profiles = list_users()
    if not profiles:
        warnings.append("no users exist yet")

    current_user = get_current_user(required=False)
    current_user_id = None if current_user is None else str(current_user["user_id"])
    if current_user_id is None:
        check_absent_path(ACTIVE_CONFIG_DIR, failures)
        check_absent_path(ACTIVE_SLURM_DIR, failures)

    session_user_id = session.get("current_user_id")
    if session_user_id and all(str(profile["user_id"]) != str(session_user_id) for profile in profiles):
        failures.append(f"session references missing current_user_id '{session_user_id}'")

    for profile in profiles:
        user_id = str(profile["user_id"])
        try:
            load_profile(user_id)
        except Exception as exc:
            failures.append(f"failed to load profile for user '{user_id}': {exc}")
            continue

        mode = check_selected_venv(user_id, failures)
        check_user_state(user_id, failures)
        check_user_assets(user_id, mode, failures)
        if current_user_id == user_id:
            check_active_workspace(user_id, mode, failures)

    if failures:
        print("Doctor: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        return 1

    print("Doctor: OK")
    if current_user_id is None:
        print("  current user: none")
    else:
        print(f"  current user: {current_user_id}")
    print(f"  users checked: {len(profiles)}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
