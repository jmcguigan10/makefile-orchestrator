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
    resolve_python_interpreter,
    resolve_requirements_file,
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
    parser.add_argument(
        "--python",
        dest="python_selection",
        help="Optional Python version, command, or interpreter path for non-interactive pyvenv creation.",
    )
    parser.add_argument(
        "--deps-mode",
        choices=["requirements", "libraries", "none"],
        help="Dependency selection mode for non-interactive pyvenv creation.",
    )
    parser.add_argument(
        "--requirements",
        help="Requirements file to install when using --deps-mode requirements.",
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="Package spec to install when using --deps-mode libraries. Repeat as needed.",
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


def resolve_python_plan(raw_selection: str | None) -> tuple[str, str]:
    if raw_selection is None:
        return prompt_python_selection()
    return resolve_python_interpreter(raw_selection)


def dependency_plan_from_args(
    deps_mode: str | None,
    requirements_path: str | None,
    packages: list[str],
) -> tuple[str, str | None, list[str]]:
    cleaned_packages = [package.strip() for package in packages if package.strip()]
    interactive_shell = sys.stdin.isatty() and sys.stdout.isatty()
    inferred_mode = deps_mode
    if inferred_mode is None:
        if requirements_path is not None:
            inferred_mode = "requirements"
        elif cleaned_packages:
            inferred_mode = "libraries"

    if inferred_mode is None:
        return prompt_dependency_plan()

    if inferred_mode == "none":
        if requirements_path is not None or cleaned_packages:
            raise ValueError("--deps-mode none cannot be combined with --requirements or --package.")
        return inferred_mode, None, []

    if inferred_mode == "requirements":
        if cleaned_packages:
            raise ValueError("--package cannot be combined with --deps-mode requirements.")
        if requirements_path is not None:
            return inferred_mode, str(resolve_requirements_file(requirements_path)), []
        if not interactive_shell:
            raise ValueError("--requirements is required for non-interactive requirements mode.")
        return inferred_mode, str(prompt_requirements_choice()), []

    if inferred_mode == "libraries":
        if requirements_path is not None:
            raise ValueError("--requirements cannot be combined with --deps-mode libraries.")
        if cleaned_packages:
            return inferred_mode, None, cleaned_packages
        if not interactive_shell:
            raise ValueError("At least one --package is required for non-interactive libraries mode.")
        return inferred_mode, None, prompt_libraries()

    raise ValueError(f"Unsupported dependency mode '{inferred_mode}'.")


def create_user_flow(name: str | None) -> None:
    from config_utils import create_user, prompt_username

    username = name if name is not None else prompt_username("Enter a new user name:")
    profile = create_user(username)
    print(f"User successfully created! Welcome to the Pipeline {profile['username']}!")


def create_pyvenv_flow(
    default_dir: str | None,
    *,
    python_selection: str | None,
    deps_mode: str | None,
    requirements_path: str | None,
    packages: list[str],
) -> None:
    env_dir = prompt_environment_directory(default_dir) if default_dir is None else resolve_env_dir(default_dir)
    python_command, python_version = resolve_python_plan(python_selection)
    dependency_mode, requirements_path_str, resolved_packages = dependency_plan_from_args(
        deps_mode,
        requirements_path,
        packages,
    )
    plan = PyVenvPlan(
        env_dir=env_dir,
        python_command=python_command,
        python_version=python_version,
        dependency_mode=dependency_mode,
        requirements_file=None if requirements_path_str is None else Path(requirements_path_str),
        packages=resolved_packages,
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
            create_pyvenv_flow(
                args.name,
                python_selection=args.python_selection,
                deps_mode=args.deps_mode,
                requirements_path=args.requirements,
                packages=list(args.package),
            )
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
