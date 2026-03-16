from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove local make-managed state.")
    parser.add_argument(
        "--object",
        default="user",
        help="Object type to remove. Supported: user, venv.",
    )
    parser.add_argument(
        "--name",
        help="Optional user name or user id to remove instead of prompting.",
    )
    return parser


def remove_venv() -> bool:
    from venv_utils import MANAGED_VENV_DIR

    venv_path = MANAGED_VENV_DIR
    if not venv_path.exists():
        return False
    shutil.rmtree(venv_path)
    return True


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        target = args.object.strip().lower()
        if target == "venv":
            removed = remove_venv()
            if removed:
                print("Removed managed make virtual environment: .envs/venvs/make-venv")
            else:
                print("No managed make virtual environment exists at .envs/venvs/make-venv")
            return 0

        if target != "user":
            raise ValueError("Supported remove targets are 'user' and 'venv'.")

        from config_utils import get_current_user, prompt_for_removal_user, remove_user, resolve_user

        current_user = get_current_user(required=False)
        if args.name is not None:
            target_user = resolve_user(args.name)
        else:
            target_user = prompt_for_removal_user(current_user["user_id"] if current_user else None)
            if target_user is None:
                print("Removal cancelled.")
                return 0

        removed_user, new_current_user = remove_user(str(target_user["user_id"]))
        if current_user is not None and current_user["user_id"] == removed_user["user_id"]:
            if new_current_user is None:
                print(f"Removed user: {removed_user['username']}. No active user remains.")
            else:
                print(f"Removed user: {removed_user['username']}. Current user is now {new_current_user['username']}.")
        elif current_user is not None:
            print(f"Removed user: {removed_user['username']}. Current user remains {current_user['username']}.")
        elif new_current_user is not None:
            print(f"Removed user: {removed_user['username']}. Current user is now {new_current_user['username']}.")
        else:
            print(f"Removed user: {removed_user['username']}. No active user remains.")
        return 0
    except Exception as exc:
        print(f"remove failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
