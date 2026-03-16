from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from venv_utils import (
    CANCEL_SENTINEL,
    COMMON_LIBRARIES,
    MenuChoice,
    MANAGED_VENV_DIR,
    OperationCancelled,
    PyVenvPlan,
    configure_package_spec,
    create_virtualenv,
    package_key,
    prompt_custom_library,
    prompt_environment_directory,
    prompt_python_selection,
    prompt_requirements_choice,
    prompt_select,
    resolve_env_dir,
    split_package_spec,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create new stateful entities.")
    parser.add_argument(
        "--object",
        default="user",
        help="Object type to create. Supported: user, pyvenv.",
    )
    parser.add_argument(
        "--name",
        help="Optional name. For pyvenv this is used as the environment directory or venv name.",
    )
    return parser


def library_menu_choices(selected_specs: dict[str, str]) -> list[MenuChoice]:
    choices: list[MenuChoice] = []
    configured_keys = set(selected_specs.keys())

    for library in COMMON_LIBRARIES:
        key = package_key(library)
        if key in configured_keys:
            spec = selected_specs[key]
            title = [
                ("class:library-add", library),
                ("class:library-detail", f"  {spec}"),
            ]
            choices.append(MenuChoice(f"{library}  {spec}", f"package::{library}", styled_title=title))
        else:
            choices.append(MenuChoice(library, f"package::{library}", styled_title=[("class:library-missing", library)]))

    common_keys = {package_key(name) for name in COMMON_LIBRARIES}
    custom_specs = [spec for key, spec in selected_specs.items() if key not in common_keys]
    for spec in custom_specs:
        name, _ = split_package_spec(spec)
        title = [
            ("class:library-add", name),
            ("class:library-detail", f"  {spec}"),
        ]
        choices.append(MenuChoice(f"{name}  {spec}", f"package::{name}", styled_title=title))

    choices.append(
        MenuChoice(
            "Add custom library...",
            "__custom_library__",
            styled_title=[("class:custom-input", "Add custom library...")],
        )
    )
    choices.append(
        MenuChoice(
            "Finish",
            "__finish__",
            styled_title=[("class:finish", "Finish")],
        )
    )
    choices.append(
        MenuChoice(
            "Cancel / escape",
            CANCEL_SENTINEL,
            styled_title=[("class:warning", "Cancel / escape")],
        )
    )
    return choices


def prompt_libraries() -> list[str]:
    selected_specs: dict[str, str] = {}

    while True:
        selected = prompt_select(
            "Select a library to configure. Selected libraries are shown in green.",
            library_menu_choices(selected_specs),
            default="__finish__" if selected_specs else None,
            use_shortcuts=False,
        )
        if selected == "__finish__":
            return list(selected_specs.values())

        if selected == CANCEL_SENTINEL:
            raise OperationCancelled("Venv creation cancelled.")

        if selected == "__custom_library__":
            name, spec = prompt_custom_library()
            if spec is not None:
                selected_specs[package_key(name)] = spec
            continue

        if not selected.startswith("package::"):
            raise ValueError(f"Unknown package selector '{selected}'.")
        package_name = selected.split("::", 1)[1]
        key = package_key(package_name)
        current_spec = selected_specs.get(key)
        spec = configure_package_spec(package_name, current_spec=current_spec)
        if spec is not None:
            selected_specs[key] = spec


def prompt_dependency_plan() -> tuple[str, str | None, list[str]]:
    dependency_mode = prompt_select(
        "How would you like to choose dependencies?",
        [
            MenuChoice("Use a requirements file", "requirements"),
            MenuChoice("Select libraries interactively", "libraries"),
            MenuChoice("No additional dependencies", "none"),
        ],
        default="libraries",
    )
    if dependency_mode == "requirements":
        return dependency_mode, str(prompt_requirements_choice()), []
    if dependency_mode == "libraries":
        return dependency_mode, None, prompt_libraries()
    return dependency_mode, None, []


def create_user_flow(name: str | None) -> None:
    from config_utils import create_user, prompt_username

    username = name if name is not None else prompt_username("Enter a new user name:")
    profile = create_user(username)
    print(f"User successfully created! Welcome to the Pipeline {profile['username']}!")


def create_pyvenv_flow(default_dir: str | None) -> None:
    env_dir = prompt_environment_directory(default_dir) if default_dir is None else resolve_env_dir(default_dir)
    python_command, python_version = prompt_python_selection()
    dependency_mode, requirements_path_str, packages = prompt_dependency_plan()
    plan = PyVenvPlan(
        env_dir=env_dir,
        python_command=python_command,
        python_version=python_version,
        dependency_mode=dependency_mode,
        requirements_file=None if requirements_path_str is None else Path(requirements_path_str),
        packages=packages,
        managed_env=env_dir.resolve() == MANAGED_VENV_DIR.resolve(),
    )
    create_virtualenv(plan)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.object == "user":
            create_user_flow(args.name)
            return 0

        if args.object == "pyvenv":
            create_pyvenv_flow(args.name)
            return 0

        raise ValueError("Supported create targets are 'user' and 'pyvenv'.")
    except subprocess.CalledProcessError as exc:
        print(f"new failed: command exited with status {exc.returncode}", file=sys.stderr)
        return 1
    except OperationCancelled as exc:
        print(str(exc))
        return 0
    except Exception as exc:
        print(f"new failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
