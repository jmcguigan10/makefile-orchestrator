from __future__ import annotations

import argparse
import sys

from config_utils import (
    get_current_user,
    load_env_state,
    prompt_for_env_mode,
    prompt_for_user,
    prompt_username,
    resolve_user,
    rename_current_user,
    set_current_user_env_mode,
    switch_user,
)
from venv_utils import get_venv_by_name, prompt_for_venv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Change active user settings.")
    parser.add_argument(
        "--config",
        "-cfg",
        help="Change target. Supported values: user, username, env-mode.",
    )
    parser.add_argument(
        "--value",
        "-val",
        help="New value for the selected user command.",
    )
    parser.add_argument(
        "--venv",
        help="Virtual environment to use for env-mode changes.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        requested = args.config.strip() if args.config else ""
        normalized = requested.lower()

        if normalized == "user":
            current_user = get_current_user(required=False)
            if args.value is not None:
                target_user = resolve_user(args.value)
            else:
                target_user = prompt_for_user(current_user["user_id"] if current_user else None)
            changed, previous_user, active_user = switch_user(target_user)
            if not changed:
                print(f"User already active: {active_user['username']}")
            elif previous_user is None:
                print(f"Current user set to {active_user['username']}")
            else:
                print(f"Switched user: {previous_user['username']} -> {active_user['username']}")
            return 0

        if normalized == "username":
            current_user = get_current_user(required=True)
            assert current_user is not None
            new_username = args.value if args.value is not None else prompt_username(
                "Enter a new username:",
                default=current_user["username"],
            )
            changed, updated_user, old_name, new_name = rename_current_user(new_username)
            if not changed:
                print(f"Username already set to {new_name}")
            else:
                print(f"Renamed user: {old_name} -> {updated_user['username']}")
            return 0

        if normalized in {"env-mode", "env_mode", "envmode"}:
            current_user = get_current_user(required=True)
            assert current_user is not None
            current_state = load_env_state(str(current_user["user_id"]))
            mode = args.value if args.value is not None else prompt_for_env_mode(current_state.get("mode"))
            if args.venv is not None:
                selected_venv = get_venv_by_name(args.venv)
            else:
                selected_venv = prompt_for_venv("Select a virtual environment for this mode:")
            changed, updated_state, old_mode, old_venv = set_current_user_env_mode(mode, selected_venv.name)
            if not changed:
                print(
                    "Env mode already active: "
                    f"{updated_state.get('mode') or 'unset'} / {updated_state.get('venv_name') or 'none'}"
                )
            else:
                print(
                    "Updated env mode: "
                    f"{old_mode or 'unset'} / {old_venv or 'none'} -> "
                    f"{updated_state.get('mode') or 'unset'} / {updated_state.get('venv_name') or 'none'}"
                )
            return 0

        if requested:
            raise ValueError(f"Unsupported change target '{requested}'. Use 'make edit {requested}' for config edits.")
        raise ValueError(
            "Use 'make change user', 'make change username', or 'make change env-mode'. "
            "Config edits moved to 'make edit <config>'."
        )
    except Exception as exc:
        print(f"change failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
