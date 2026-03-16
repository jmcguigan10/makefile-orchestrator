from __future__ import annotations

import argparse
import subprocess
import sys

from venv_utils import (
    CANCEL_SENTINEL,
    COMMON_LIBRARIES,
    MenuChoice,
    OperationCancelled,
    apply_package_changes,
    configure_package_spec,
    get_venv_by_name,
    installed_package_map,
    package_key,
    plain_relative,
    prompt_confirm,
    prompt_custom_library,
    prompt_for_venv,
    prompt_select,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Edit managed virtual environments and configs.")
    parser.add_argument(
        "--object",
        default="venvs",
        help="Object type to edit. Supported: venvs or a config name.",
    )
    parser.add_argument(
        "--config",
        "-cfg",
        help="Optional config name to edit. Overrides --object for config edits.",
    )
    parser.add_argument(
        "--name",
        help="Optional virtual environment name to edit instead of prompting.",
    )
    parser.add_argument(
        "--value",
        "-val",
        help="Optional new value when editing a config.",
    )
    return parser


def package_display_name(key: str, installed: dict[str, dict[str, str]], pending: dict[str, dict[str, str]]) -> str:
    if key in installed:
        return installed[key]["name"]
    if key in pending:
        return pending[key]["name"]
    return key


def library_status(key: str, installed: dict[str, dict[str, str]], pending: dict[str, dict[str, str]]) -> str:
    if key in pending:
        return pending[key]["action"]
    if key in installed:
        return "existing"
    return "missing"


def library_detail(key: str, installed: dict[str, dict[str, str]], pending: dict[str, dict[str, str]]) -> str:
    if key in pending:
        action = pending[key]["action"]
        if action in {"add", "edit"}:
            return f"{pending[key]['spec']} ({action})"
        return f"{pending[key]['name']}=={pending[key]['version']} (remove)"
    if key in installed:
        package = installed[key]
        return f"{package['name']}=={package['version']}"
    return ""


def library_style_class(status: str) -> str:
    if status == "remove":
        return "library-remove"
    if status == "edit":
        return "library-edit"
    if status == "add":
        return "library-add"
    if status == "existing":
        return "library-existing"
    return "library-missing"


def build_library_choices(installed: dict[str, dict[str, str]], pending: dict[str, dict[str, str]]) -> list[MenuChoice]:
    keys = [package_key(name) for name in COMMON_LIBRARIES]
    extra_keys = sorted(key for key in installed if key not in keys)
    extra_pending = sorted(key for key in pending if key not in keys and key not in installed)
    ordered_keys = keys + extra_keys + extra_pending

    choices: list[MenuChoice] = []
    for key in ordered_keys:
        display_name = package_display_name(key, installed, pending)
        detail = library_detail(key, installed, pending)
        style_class = library_style_class(library_status(key, installed, pending))
        title = [(f"class:{style_class}", display_name)]
        if detail:
            title.append(("class:library-detail", f"  {detail}"))
        choices.append(MenuChoice(f"{display_name}  {detail}".strip(), f"package::{key}", styled_title=title))

    choices.append(
        MenuChoice(
            "Add custom library...",
            "__custom_library__",
            styled_title=[("class:custom-input", "Add custom library...")],
        )
    )
    choices.append(MenuChoice("Finish", "__finish__", styled_title=[("class:finish", "Finish")]))
    choices.append(
        MenuChoice(
            "Cancel / escape",
            CANCEL_SENTINEL,
            styled_title=[("class:warning", "Cancel / escape")],
        )
    )
    return choices


def prompt_library_action(display_name: str) -> str:
    return prompt_select(
        f"What do you want to do with {display_name}?",
        [
            MenuChoice("Edit", "edit"),
            MenuChoice("Remove", "remove"),
            MenuChoice("Back", "back"),
        ],
        default="back",
    )


def update_pending_change(
    key: str,
    installed: dict[str, dict[str, str]],
    pending: dict[str, dict[str, str]],
) -> None:
    installed_package = installed.get(key)
    current_pending = pending.get(key)
    display_name = package_display_name(key, installed, pending)

    if installed_package is None and current_pending is None:
        spec = configure_package_spec(display_name)
        if spec is None:
            return
        pending[key] = {
            "action": "add",
            "name": display_name,
            "spec": spec,
        }
        return

    action = prompt_library_action(display_name)
    if action == "back":
        return

    if action == "edit":
        current_spec = None
        if current_pending is not None and current_pending["action"] in {"add", "edit"}:
            current_spec = current_pending["spec"]
        elif installed_package is not None:
            current_spec = f"{installed_package['name']}=={installed_package['version']}"
        spec = configure_package_spec(display_name, current_spec=current_spec)
        if spec is None:
            return
        pending[key] = {
            "action": "edit" if installed_package is not None else "add",
            "name": display_name,
            "spec": spec,
        }
        return

    if current_pending is not None and current_pending["action"] == "add" and installed_package is None:
        pending.pop(key, None)
        return

    if installed_package is None:
        return

    pending[key] = {
        "action": "remove",
        "name": installed_package["name"],
        "version": installed_package["version"],
    }


def edit_venv_libraries(venv_name: str) -> None:
    venv = get_venv_by_name(venv_name)
    if venv.managed:
        should_continue = prompt_confirm(
            "Are you sure you want to edit make-venv? This can break the make tooling.",
            default=False,
        )
        if not should_continue:
            print("Edit cancelled.")
            return

    installed = installed_package_map(venv.path)
    pending: dict[str, dict[str, str]] = {}

    while True:
        selected = prompt_select(
            f"Edit libraries for {venv.name}. Existing libraries are blue.",
            build_library_choices(installed, pending),
            default="__finish__" if pending else None,
            use_shortcuts=False,
        )

        if selected == "__finish__":
            break

        if selected == CANCEL_SENTINEL:
            raise OperationCancelled("Edit cancelled.")

        if selected == "__custom_library__":
            name, spec = prompt_custom_library()
            if spec is not None:
                key = package_key(name)
                pending[key] = {
                    "action": "edit" if key in installed else "add",
                    "name": installed.get(key, {"name": name})["name"],
                    "spec": spec,
                }
            continue

        if not selected.startswith("package::"):
            raise ValueError(f"Unknown package selector '{selected}'.")
        update_pending_change(selected.split("::", 1)[1], installed, pending)

    remove_packages = [change["name"] for change in pending.values() if change["action"] == "remove"]
    install_specs = [change["spec"] for change in pending.values() if change["action"] in {"add", "edit"}]
    if not remove_packages and not install_specs:
        print(f"No changes queued for {venv.name}.")
        return

    apply_package_changes(venv.path, remove_packages=remove_packages, install_specs=install_specs)
    print(f"Updated {venv.name} at {plain_relative(venv.path)}.")


def edit_config_value(requested: str, raw_value: str | None) -> None:
    from config_utils import (
        apply_config_change,
        coerce_value,
        get_configs,
        load_store,
        prompt_for_config,
        prompt_for_value,
        resolve_config_name,
    )

    store = load_store()
    configs = get_configs(store)

    if requested:
        name = resolve_config_name(configs, requested)
    else:
        name = prompt_for_config(configs)

    entry = configs[name]
    value_text = raw_value if raw_value is not None else prompt_for_value(name, entry)
    updated_value = coerce_value(entry, value_text)

    _, message = apply_config_change(name, updated_value)
    print(message)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        requested_config = args.config.strip() if args.config else ""
        target = requested_config or args.object.strip()
        normalized_target = target.lower()

        if normalized_target == "venvs":
            if args.name is not None:
                selected_venv = get_venv_by_name(args.name)
            else:
                selected_venv = prompt_for_venv()
            edit_venv_libraries(selected_venv.name)
            return 0

        if normalized_target in {"user", "username"}:
            raise ValueError("Use 'make change user' or 'make change username' for user management.")

        edit_config_value(target, args.value)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"edit failed: command exited with status {exc.returncode}", file=sys.stderr)
        return 1
    except OperationCancelled as exc:
        print(str(exc))
        return 0
    except Exception as exc:
        print(f"edit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
