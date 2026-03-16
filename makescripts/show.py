from __future__ import annotations

import argparse
import sys

from config_utils import (
    ALL_SENTINELS,
    get_configs,
    load_store,
    parse_cli_bool,
    print_config_details,
    print_config_table,
    print_current_env_mode,
    print_current_user,
    print_global_history_window,
    print_history_window,
    resolve_config_name,
)
from venv_utils import ansi_red, get_installed_packages, list_virtualenvs, plain_relative


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show MLP configuration values.")
    parser.add_argument(
        "--config",
        "-cfg",
        default="all",
        help="Config name to show, or 'all' to list every config. Special value: user.",
    )
    parser.add_argument(
        "--back",
        type=int,
        default=0,
        help="History offset to start from when showing a config history window.",
    )
    parser.add_argument(
        "--list",
        dest="list_count",
        type=int,
        default=1,
        help="Number of history entries to show starting from --back. Use 0 for all remaining entries.",
    )
    parser.add_argument(
        "--global",
        dest="global_flag",
        default="false",
        help="Show the config through global config-state history instead of its local change log.",
    )
    return parser


def print_venv_inventory() -> None:
    venvs = list_virtualenvs()
    print("Virtual environments:")
    if not venvs:
        print("  (none)")
        return

    for info in venvs:
        heading = f"{info.name} (managed)" if info.managed else info.name
        display = ansi_red(heading) if info.managed else heading
        print(f"  {display}")
        print(f"    path: {plain_relative(info.path)}")
        packages = get_installed_packages(info.path)
        if not packages:
            print("    libraries:")
            print("      (none)")
            continue
        print("    libraries:")
        for package in packages:
            print(f"      - {package['name']}=={package['version']}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        requested = args.config.strip()
        use_global_history = parse_cli_bool(args.global_flag)
        if requested.lower() == "venvs":
            if use_global_history:
                raise ValueError("global=true does not apply to 'show venvs'.")
            if args.back != 0 or args.list_count != 1:
                raise ValueError("History windows do not apply to 'show venvs'.")
            print_venv_inventory()
            return 0

        if requested.lower() == "user":
            if use_global_history:
                raise ValueError("global=true does not apply to 'show user'.")
            if args.back != 0 or args.list_count != 1:
                raise ValueError("History windows do not apply to 'show user'.")
            print_current_user()
            return 0

        if requested.lower() in {"env-mode", "env_mode", "envmode"}:
            if use_global_history:
                raise ValueError("global=true does not apply to 'show env-mode'.")
            if args.back != 0 or args.list_count != 1:
                raise ValueError("History windows do not apply to 'show env-mode'.")
            print_current_env_mode()
            return 0

        store = load_store()
        configs = get_configs(store)
        if requested.lower() in ALL_SENTINELS:
            if use_global_history:
                raise ValueError("global=true requires a specific config, not 'all'.")
            if args.back != 0 or args.list_count != 1:
                raise ValueError("History windows require a specific config, not 'all'.")
            print_config_table(configs)
            return 0

        name = resolve_config_name(configs, requested)
        if use_global_history:
            print_global_history_window(name, store, args.back, args.list_count)
            return 0
        if args.back > 0 or args.list_count != 1:
            print_history_window(name, configs[name], args.back, args.list_count)
            return 0

        print_config_details(name, configs[name])
        return 0
    except Exception as exc:
        print(f"show failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
