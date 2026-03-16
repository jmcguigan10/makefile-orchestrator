from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys
from typing import Any

try:
    import questionary
except ImportError:  # pragma: no cover - fallback for system Python paths like remove venv
    questionary = None
import yaml

from env_mode_utils import (
    INTERACTIVE_MODE,
    NON_INTERACTIVE_MODE,
    activate_user_mode_workspace,
    default_env_state,
    describe_env_workspace,
    deactivate_active_workspace,
    normalize_env_mode,
    refresh_user_mode_assets,
    remove_user_mode_assets,
)


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_CONFIG_PATH = ROOT / "mlp_configs.yaml"
STATE_DIR = ROOT / "state"
USERS_DIR = STATE_DIR / "users"
SESSION_PATH = STATE_DIR / "session.yaml"

BOOLEAN_TRUE = {"1", "true", "t", "yes", "y", "on"}
BOOLEAN_FALSE = {"0", "false", "f", "no", "n", "off"}
ALL_SENTINELS = {"all", "configs", "list"}
CANCEL_SENTINEL = "__cancel__"
MISSING = object()


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_name(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def normalize_username(name: str) -> str:
    return normalize_name(" ".join(name.strip().split()))


def slugify_name(name: str) -> str:
    collapsed = "_".join(name.strip().split())
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", collapsed).strip("_").lower()
    return cleaned or "user"


def validate_username(name: str) -> str:
    trimmed = " ".join(name.strip().split())
    if not trimmed:
        raise ValueError("Username cannot be empty.")
    return trimmed


def should_use_questionary() -> bool:
    return questionary is not None and sys.stdin.isatty() and sys.stdout.isatty()


def fallback_prompt_text(message: str) -> str:
    response = input(message).strip()
    if not response:
        raise ValueError("No value entered.")
    return response


def fallback_prompt_with_options(label: str, options: list[str], current: Any) -> str:
    print(f"Available values for {label}:")
    for idx, option in enumerate(options, start=1):
        current_marker = " (current)" if str(option) == str(current) else ""
        print(f"  {idx}. {option}{current_marker}")
    response = input("Select an option by number or value: ").strip()
    if not response:
        raise ValueError("No value selected.")
    if response.isdigit():
        index = int(response) - 1
        if index < 0 or index >= len(options):
            raise ValueError(f"Selection {response} is out of range.")
        return options[index]
    return response


def prompt_text(message: str, default: str | None = None) -> str:
    if should_use_questionary():
        if default is None:
            response = questionary.text(message).ask()
        else:
            response = questionary.text(message, default=default).ask()
        if response is None or not response.strip():
            raise ValueError("No value entered.")
        return response.strip()
    return fallback_prompt_text(message)


def prompt_select(message: str, choices: list[questionary.Choice | str]) -> str:
    if should_use_questionary():
        response = questionary.select(message, choices=choices, use_shortcuts=True).ask()
        if response is None:
            raise ValueError("Selection cancelled.")
        return response

    normalized_choices: list[str] = []
    for choice in choices:
        if isinstance(choice, str):
            normalized_choices.append(choice)
        else:
            normalized_choices.append(str(choice.value))
    return fallback_prompt_with_options(message, normalized_choices, "")


def prompt_username(message: str, default: str | None = None) -> str:
    return validate_username(prompt_text(message, default=default))


def default_session() -> dict[str, Any]:
    return {
        "current_user_id": None,
        "undo_stack": [],
        "redo_stack": [],
    }


def load_session() -> dict[str, Any]:
    if not SESSION_PATH.exists():
        return default_session()

    with SESSION_PATH.open("r", encoding="utf-8") as handle:
        session = yaml.safe_load(handle) or {}

    if not isinstance(session, dict):
        raise ValueError(f"{SESSION_PATH} must contain a mapping.")

    merged = default_session()
    merged.update(session)
    if not isinstance(merged["undo_stack"], list) or not isinstance(merged["redo_stack"], list):
        raise ValueError(f"{SESSION_PATH} must define undo_stack and redo_stack as lists.")
    return merged


def save_session(session: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with SESSION_PATH.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(session, handle, sort_keys=False, allow_unicode=False)


def user_dir(user_id: str) -> Path:
    return USERS_DIR / user_id


def profile_path(user_id: str) -> Path:
    return user_dir(user_id) / "profile.yaml"


def configs_path(user_id: str) -> Path:
    return user_dir(user_id) / "configs.yaml"


def user_logs_dir(user_id: str) -> Path:
    return user_dir(user_id) / "logs"


def user_history_dir(user_id: str) -> Path:
    return user_logs_dir(user_id) / "config_history"


def history_path(name: str, user_id: str) -> Path:
    return user_history_dir(user_id) / f"{name}.yaml"


def global_history_path(user_id: str) -> Path:
    return user_logs_dir(user_id) / "global_history.yaml"


def env_state_path(user_id: str) -> Path:
    return user_dir(user_id) / "env_state.yaml"


def load_template_store() -> dict[str, Any]:
    with TEMPLATE_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        store = yaml.safe_load(handle) or {}
    if "configs" not in store or not isinstance(store["configs"], dict):
        raise ValueError(f"{TEMPLATE_CONFIG_PATH} must define a top-level 'configs' mapping.")
    return store


def save_profile(profile: dict[str, Any]) -> None:
    user_dir(profile["user_id"]).mkdir(parents=True, exist_ok=True)
    with profile_path(profile["user_id"]).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(profile, handle, sort_keys=False, allow_unicode=False)


def load_profile(user_id: str) -> dict[str, Any]:
    path = profile_path(user_id)
    if not path.exists():
        raise ValueError(f"Unknown user id '{user_id}'.")
    with path.open("r", encoding="utf-8") as handle:
        profile = yaml.safe_load(handle) or {}
    if not isinstance(profile, dict):
        raise ValueError(f"{path} must contain a mapping.")
    profile["user_id"] = user_id
    if "username" not in profile:
        raise ValueError(f"{path} must define 'username'.")
    return profile


def list_users() -> list[dict[str, Any]]:
    if not USERS_DIR.exists():
        return []

    profiles: list[dict[str, Any]] = []
    for child in sorted(USERS_DIR.iterdir()):
        if not child.is_dir():
            continue
        if not profile_path(child.name).exists():
            continue
        profiles.append(load_profile(child.name))
    profiles.sort(key=lambda profile: profile["username"].lower())
    return profiles


def load_env_state(user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    path = env_state_path(user_id)
    merged = default_env_state()
    if not path.exists():
        return merged

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping.")

    merged.update(payload)
    merged["mode"] = normalize_env_mode(merged.get("mode"))
    return merged


def save_env_state_data(user_id: str, env_state: dict[str, Any]) -> None:
    payload = default_env_state()
    payload.update(env_state)
    payload["mode"] = normalize_env_mode(payload.get("mode"))
    user_dir(user_id).mkdir(parents=True, exist_ok=True)
    with env_state_path(user_id).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def sync_user_environment_assets(user_id: str, store: dict[str, Any] | None = None) -> None:
    if not profile_path(user_id).exists():
        return

    profile = load_profile(user_id)
    if store is None:
        if not configs_path(user_id).exists():
            return
        with configs_path(user_id).open("r", encoding="utf-8") as handle:
            store = yaml.safe_load(handle) or {}
    if "configs" not in store or not isinstance(store["configs"], dict):
        raise ValueError(f"{configs_path(user_id)} must define a top-level 'configs' mapping.")

    env_state = load_env_state(user_id)
    snapshot = snapshot_config_values(store)
    refresh_user_mode_assets(user_id, str(profile["username"]), snapshot, env_state)

    session = load_session()
    if session.get("current_user_id") == user_id:
        activate_user_mode_workspace(user_id, env_state)


def save_env_state(env_state: dict[str, Any], user_id: str | None = None) -> None:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])
    save_env_state_data(user_id, env_state)
    sync_user_environment_assets(user_id)


def prompt_for_env_mode(current_mode: str | None = None) -> str:
    options = [INTERACTIVE_MODE, NON_INTERACTIVE_MODE]
    if should_use_questionary():
        choices = [
            questionary.Choice(
                title=f"{mode}{' (current)' if mode == current_mode else ''}",
                value=mode,
            )
            for mode in options
        ]
        return prompt_select("Select an environment mode:", choices)
    return normalize_env_mode(fallback_prompt_with_options("env-mode", options, current_mode))


def print_current_env_mode() -> None:
    user = get_current_user(required=True)
    assert user is not None
    env_state = load_env_state(str(user["user_id"]))
    summary = describe_env_workspace(str(user["user_id"]), str(user["username"]), env_state)
    print(f"user: {summary['user']}")
    if summary["mode"] is None:
        print("env-mode: not set")
        print("venv: not set")
        print("active configs: hidden")
        print("active slurm: hidden")
        return

    print(f"env-mode: {summary['mode']}")
    venv_info = summary["venv"]
    if venv_info["name"] is None:
        print("venv: not set")
    else:
        venv_line = str(venv_info["name"])
        if venv_info["relative_path"]:
            venv_line += f" ({venv_info['relative_path']})"
        if not venv_info["exists"]:
            venv_line += " [missing]"
        print(f"venv: {venv_line}")
    print(f"hidden configs: {summary['hidden_configs']}")
    print(f"active configs: {summary['active_configs'] or 'hidden'}")
    print(f"hidden slurm: {summary['hidden_slurm'] or 'n/a'}")
    print(f"active slurm: {summary['active_slurm'] or 'hidden'}")


def apply_env_state_without_action(user_id: str, mode: str | None, venv_name: str | None) -> dict[str, Any]:
    env_state = load_env_state(user_id)
    env_state["mode"] = normalize_env_mode(mode)
    env_state["venv_name"] = venv_name
    env_state["updated_at"] = current_timestamp()
    save_env_state(env_state, user_id)
    return env_state


def set_current_user_env_mode(mode: str, venv_name: str) -> tuple[bool, dict[str, Any], str | None, str | None]:
    from venv_utils import get_venv_by_name

    user = get_current_user(required=True)
    assert user is not None
    user_id = str(user["user_id"])
    resolved_mode = normalize_env_mode(mode)
    if resolved_mode is None:
        raise ValueError("Env mode cannot be empty.")

    selected_venv = get_venv_by_name(venv_name)
    current_state = load_env_state(user_id)
    previous_mode = current_state.get("mode")
    previous_venv = current_state.get("venv_name")
    if previous_mode == resolved_mode and previous_venv == selected_venv.name:
        return False, current_state, previous_mode, previous_venv

    updated_state = deepcopy(current_state)
    updated_state["mode"] = resolved_mode
    updated_state["venv_name"] = selected_venv.name
    updated_state["updated_at"] = current_timestamp()
    save_env_state(updated_state, user_id)

    session = load_session()
    session["current_user_id"] = user_id
    session["undo_stack"].append(
        {
            "kind": "env_mode_change",
            "recorded_at": current_timestamp(),
            "user_id": user_id,
            "from_mode": previous_mode,
            "from_venv_name": previous_venv,
            "to_mode": resolved_mode,
            "to_venv_name": selected_venv.name,
        }
    )
    session["redo_stack"] = []
    save_session(session)
    return True, updated_state, previous_mode, previous_venv


def get_current_user(required: bool = True) -> dict[str, Any] | None:
    session = load_session()
    user_id = session.get("current_user_id")
    if not user_id:
        if required:
            raise ValueError("No active user. Run 'make new user' first.")
        return None
    return load_profile(str(user_id))


def save_user_store(user_id: str, store: dict[str, Any]) -> None:
    user_dir(user_id).mkdir(parents=True, exist_ok=True)
    with configs_path(user_id).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(store, handle, sort_keys=False, allow_unicode=False)
    sync_user_environment_assets(user_id, store)


def load_store(user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    path = configs_path(user_id)
    if not path.exists():
        save_user_store(user_id, load_template_store())

    with path.open("r", encoding="utf-8") as handle:
        store = yaml.safe_load(handle) or {}
    if "configs" not in store or not isinstance(store["configs"], dict):
        raise ValueError(f"{path} must define a top-level 'configs' mapping.")
    return store


def save_store(store: dict[str, Any], user_id: str | None = None) -> None:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])
    save_user_store(user_id, store)


def get_configs(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return store["configs"]


def snapshot_config_values(store: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(entry["value"]) for name, entry in get_configs(store).items()}


def compare_snapshots(previous_snapshot: dict[str, Any], current_snapshot: dict[str, Any]) -> list[str]:
    changed_names: list[str] = []
    for name in current_snapshot:
        if previous_snapshot.get(name) != current_snapshot.get(name):
            changed_names.append(name)
    return changed_names


def alias_map(configs: dict[str, dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, entry in configs.items():
        aliases[normalize_name(name)] = name
        for alias in entry.get("aliases", []):
            aliases[normalize_name(str(alias))] = name
    return aliases


def resolve_config_name(configs: dict[str, dict[str, Any]], requested: str) -> str:
    mapping = alias_map(configs)
    normalized = normalize_name(requested)
    if normalized not in mapping:
        known = ", ".join(configs.keys())
        raise KeyError(f"Unknown config '{requested}'. Known configs: {known}")
    return mapping[normalized]


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    return str(value)


def describe_entry(name: str, entry: dict[str, Any]) -> str:
    return f"{name:<24} {format_value(entry['value']):<18} ({entry['type']})"


def print_config_table(configs: dict[str, dict[str, Any]]) -> None:
    user = get_current_user(required=False)
    if user is not None:
        print(f"user: {user['username']}")
    print("Current configs:")
    for name, entry in configs.items():
        print(f"  {describe_entry(name, entry)}")


def print_config_details(name: str, entry: dict[str, Any]) -> None:
    user = get_current_user(required=False)
    if user is not None:
        print(f"user: {user['username']}")
    print(f"name: {name}")
    print(f"type: {entry['type']}")
    print(f"value: {format_value(entry['value'])}")
    if entry.get("description"):
        print(f"description: {entry['description']}")
    if entry.get("aliases"):
        print("aliases: " + ", ".join(str(alias) for alias in entry["aliases"]))
    if "choices" in entry:
        print("choices: " + ", ".join(str(choice) for choice in entry["choices"]))
    if "min" in entry:
        print(f"min: {entry['min']}")
    if "max" in entry:
        print(f"max: {entry['max']}")


def make_user_id(username: str) -> str:
    base = slugify_name(username)
    candidate = base
    suffix = 2
    while user_dir(candidate).exists():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def ensure_unique_username(username: str, exclude_user_id: str | None = None) -> None:
    normalized = normalize_username(username)
    for profile in list_users():
        if exclude_user_id is not None and profile["user_id"] == exclude_user_id:
            continue
        if normalize_username(profile["username"]) == normalized:
            raise ValueError(f"User '{username}' already exists.")


def create_user(username: str) -> dict[str, Any]:
    clean_name = validate_username(username)
    ensure_unique_username(clean_name)

    user_id = make_user_id(clean_name)
    now = current_timestamp()
    profile = {
        "user_id": user_id,
        "username": clean_name,
        "created_at": now,
        "updated_at": now,
    }

    save_profile(profile)
    store = deepcopy(load_template_store())
    save_user_store(user_id, store)
    save_env_state_data(user_id, default_env_state())
    save_global_history_log(
        user_id,
        {
            "entries": [
                make_global_history_entry(
                    "initial",
                    snapshot_config_values(store),
                    recorded_at=now,
                )
            ]
        },
    )

    session = load_session()
    session["current_user_id"] = user_id
    save_session(session)
    sync_user_environment_assets(user_id, store)
    return profile


def resolve_user(requested: str) -> dict[str, Any]:
    normalized = normalize_username(requested)
    for profile in list_users():
        if profile["user_id"] == requested:
            return profile
        if normalize_username(profile["username"]) == normalized:
            return profile
    known = ", ".join(profile["username"] for profile in list_users())
    raise KeyError(f"Unknown user '{requested}'. Known users: {known}")


def prompt_for_user(current_user_id: str | None = None) -> dict[str, Any]:
    profiles = list_users()
    if not profiles:
        raise ValueError("No users exist yet. Run 'make new user' first.")

    if should_use_questionary():
        choices = [
            questionary.Choice(
                title=f"{profile['username']}{' (current)' if profile['user_id'] == current_user_id else ''}",
                value=profile["user_id"],
            )
            for profile in profiles
        ]
        selected = prompt_select("Select a user:", choices)
        return load_profile(selected)

    print("Available users:")
    for index, profile in enumerate(profiles, start=1):
        current_marker = " (current)" if profile["user_id"] == current_user_id else ""
        print(f"  {index}. {profile['username']}{current_marker}")
    raw_choice = fallback_prompt_text("Select a user by number or name: ")
    if raw_choice.isdigit():
        index = int(raw_choice) - 1
        if index < 0 or index >= len(profiles):
            raise ValueError(f"Selection {raw_choice} is out of range.")
        return profiles[index]
    return resolve_user(raw_choice)


def prompt_for_removal_user(current_user_id: str | None = None) -> dict[str, Any] | None:
    profiles = list_users()
    if not profiles:
        raise ValueError("No users exist yet. Run 'make new user' first.")

    if should_use_questionary():
        choices = [
            questionary.Choice(
                title=f"{profile['username']}{' (current)' if profile['user_id'] == current_user_id else ''}",
                value=profile["user_id"],
            )
            for profile in profiles
        ]
        choices.append(questionary.Choice(title="Cancel / escape", value=CANCEL_SENTINEL))
        selected = prompt_select("Select a user to remove:", choices)
        if selected == CANCEL_SENTINEL:
            return None
        return load_profile(selected)

    print("Available users to remove:")
    for index, profile in enumerate(profiles, start=1):
        current_marker = " (current)" if profile["user_id"] == current_user_id else ""
        print(f"  {index}. {profile['username']}{current_marker}")
    print(f"  {len(profiles) + 1}. Cancel / escape")
    raw_choice = fallback_prompt_text("Select a user by number or name: ")
    if raw_choice.isdigit():
        index = int(raw_choice) - 1
        if index == len(profiles):
            return None
        if index < 0 or index >= len(profiles):
            raise ValueError(f"Selection {raw_choice} is out of range.")
        return profiles[index]
    if normalize_username(raw_choice) in {normalize_username("cancel"), normalize_username("escape")}:
        return None
    return resolve_user(raw_choice)


def switch_user(target_user: dict[str, Any]) -> tuple[bool, dict[str, Any] | None, dict[str, Any]]:
    session = load_session()
    current_user = get_current_user(required=False)

    if current_user is not None and current_user["user_id"] == target_user["user_id"]:
        return False, current_user, target_user

    session["current_user_id"] = target_user["user_id"]
    if current_user is not None:
        action = {
            "kind": "user_switch",
            "recorded_at": current_timestamp(),
            "from_user_id": current_user["user_id"],
            "to_user_id": target_user["user_id"],
        }
        session["undo_stack"].append(action)
        session["redo_stack"] = []
    save_session(session)
    sync_user_environment_assets(str(target_user["user_id"]))
    return True, current_user, target_user


def action_references_user(action: dict[str, Any], user_id: str) -> bool:
    kind = action.get("kind")
    if kind == "config_change":
        return action.get("user_id") == user_id
    if kind == "env_mode_change":
        return action.get("user_id") == user_id
    if kind == "username_change":
        return action.get("user_id") == user_id
    if kind == "user_switch":
        return action.get("from_user_id") == user_id or action.get("to_user_id") == user_id
    return False


def remove_user(user_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    profile = load_profile(user_id)
    session = load_session()

    session["undo_stack"] = [action for action in session["undo_stack"] if not action_references_user(action, user_id)]
    session["redo_stack"] = [action for action in session["redo_stack"] if not action_references_user(action, user_id)]

    remaining_users = [entry for entry in list_users() if entry["user_id"] != user_id]
    new_current_user: dict[str, Any] | None = None
    if session.get("current_user_id") == user_id:
        if remaining_users:
            new_current_user = remaining_users[0]
            session["current_user_id"] = new_current_user["user_id"]
        else:
            session["current_user_id"] = None

    remove_user_mode_assets(user_id)
    shutil.rmtree(user_dir(user_id))
    save_session(session)
    if new_current_user is not None:
        sync_user_environment_assets(str(new_current_user["user_id"]))
    elif session.get("current_user_id") is None:
        deactivate_active_workspace()
    return profile, new_current_user


def remove_venv() -> bool:
    venv_path = ROOT / ".venv"
    if not venv_path.exists():
        return False
    shutil.rmtree(venv_path)
    return True


def rename_user(user_id: str, new_username: str) -> tuple[bool, str, str]:
    clean_name = validate_username(new_username)
    profile = load_profile(user_id)
    old_name = str(profile["username"])
    if clean_name == old_name:
        return False, old_name, clean_name

    ensure_unique_username(clean_name, exclude_user_id=user_id)
    profile["username"] = clean_name
    profile["updated_at"] = current_timestamp()
    save_profile(profile)
    sync_user_environment_assets(user_id)
    return True, old_name, clean_name


def rename_current_user(new_username: str) -> tuple[bool, dict[str, Any], str, str]:
    user = get_current_user(required=True)
    assert user is not None
    changed, old_name, clean_name = rename_user(str(user["user_id"]), new_username)
    if not changed:
        return False, user, old_name, clean_name

    session = load_session()
    session["current_user_id"] = user["user_id"]
    session["undo_stack"].append(
        {
            "kind": "username_change",
            "recorded_at": current_timestamp(),
            "user_id": user["user_id"],
            "from_username": old_name,
            "to_username": clean_name,
        }
    )
    session["redo_stack"] = []
    save_session(session)
    return True, load_profile(str(user["user_id"])), old_name, clean_name


def print_current_user() -> None:
    user = get_current_user(required=True)
    assert user is not None
    print(f"current user: {user['username']}")


def parse_bool(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in BOOLEAN_TRUE:
        return True
    if normalized in BOOLEAN_FALSE:
        return False
    raise ValueError("Expected a boolean value such as true/false, yes/no, or 1/0.")


def parse_list(raw_value: str, caster: Any) -> list[Any]:
    parts = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not parts:
        raise ValueError("Expected a comma-separated list.")
    return [caster(part) for part in parts]


def validate_numeric(value: Any, entry: dict[str, Any]) -> None:
    min_value = entry.get("min")
    max_value = entry.get("max")
    if isinstance(value, list):
        for item in value:
            validate_numeric(item, entry)
        return
    if min_value is not None and value < min_value:
        raise ValueError(f"Value {value} is below the minimum of {min_value}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"Value {value} is above the maximum of {max_value}.")


def coerce_value(entry: dict[str, Any], raw_value: str) -> Any:
    entry_type = entry["type"]
    if entry_type == "int":
        value = int(raw_value)
        validate_numeric(value, entry)
        return value
    if entry_type == "float":
        value = float(raw_value)
        validate_numeric(value, entry)
        return value
    if entry_type == "bool":
        return parse_bool(raw_value)
    if entry_type == "choice":
        choices = [str(choice) for choice in entry.get("choices", [])]
        if raw_value not in choices:
            raise ValueError(f"Expected one of: {', '.join(choices)}")
        return raw_value
    if entry_type == "int_list":
        value = parse_list(raw_value, int)
        validate_numeric(value, entry)
        return value
    if entry_type == "float_list":
        value = parse_list(raw_value, float)
        validate_numeric(value, entry)
        return value
    if entry_type == "string_list":
        return parse_list(raw_value, str)
    if entry_type == "str":
        return raw_value
    raise ValueError(f"Unsupported config type: {entry_type}")


def prompt_for_config(configs: dict[str, dict[str, Any]]) -> str:
    if should_use_questionary():
        choices = [
            questionary.Choice(
                title=f"{name:<24} {format_value(entry['value']):<18} ({entry['type']})",
                value=name,
            )
            for name, entry in configs.items()
        ]
        return prompt_select("Select a config to change:", choices)

    print("Available configs:")
    for index, (name, entry) in enumerate(configs.items(), start=1):
        print(f"  {index:>2}. {describe_entry(name, entry)}")
    print()
    raw_choice = fallback_prompt_text("Select a config by number or name: ")
    if raw_choice.isdigit():
        index = int(raw_choice) - 1
        names = list(configs.keys())
        if index < 0 or index >= len(names):
            raise ValueError(f"Selection {raw_choice} is out of range.")
        return names[index]
    return resolve_config_name(configs, raw_choice)


def prompt_for_value(name: str, entry: dict[str, Any]) -> str:
    current = entry["value"]
    entry_type = entry["type"]
    print(f"Changing '{name}'")
    print(f"Current value: {format_value(current)}")
    if entry.get("description"):
        print(entry["description"])
    if entry_type == "bool":
        if should_use_questionary():
            choices = [
                questionary.Choice(
                    title=f"{option}{' (current)' if option == format_value(current) else ''}",
                    value=option,
                )
                for option in ["true", "false"]
            ]
            return prompt_select(f"Select a new value for {name}:", choices)
        return fallback_prompt_with_options(name, ["true", "false"], format_value(current))
    if entry_type == "choice":
        options = [str(choice) for choice in entry.get("choices", [])]
        if should_use_questionary():
            choices = [
                questionary.Choice(
                    title=f"{option}{' (current)' if option == str(current) else ''}",
                    value=option,
                )
                for option in options
            ]
            return prompt_select(f"Select a new value for {name}:", choices)
        return fallback_prompt_with_options(name, options, current)
    prompt = "Enter a new value"
    if entry_type in {"int_list", "float_list", "string_list"}:
        prompt += " (comma-separated)"
    if current not in (None, ""):
        prompt += f" [{format_value(current)}]"
    prompt += ": "
    return prompt_text(prompt, default=format_value(current))


def make_global_history_entry(
    event: str,
    snapshot: dict[str, Any],
    changed_config: str | None = None,
    previous_value: Any = MISSING,
    new_value: Any = MISSING,
    recorded_at: str | None = None,
    changed_configs: list[str] | None = None,
) -> dict[str, Any]:
    entry = {
        "recorded_at": recorded_at or current_timestamp(),
        "event": event,
        "snapshot": deepcopy(snapshot),
    }
    if changed_config is not None:
        entry["changed_config"] = changed_config
    if previous_value is not MISSING:
        entry["previous_value"] = deepcopy(previous_value)
    if new_value is not MISSING:
        entry["new_value"] = deepcopy(new_value)
    if changed_configs:
        entry["changed_configs"] = list(changed_configs)
    return entry


def load_global_history_log(user_id: str) -> dict[str, Any]:
    path = global_history_path(user_id)
    if not path.exists():
        return rebuild_global_history_log(user_id)

    with path.open("r", encoding="utf-8") as handle:
        log = yaml.safe_load(handle) or {}

    if not isinstance(log, dict):
        raise ValueError(f"{path} must contain a mapping.")

    entries = log.setdefault("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path} must define 'entries' as a list.")

    if not entries:
        return rebuild_global_history_log(user_id)

    return log


def save_global_history_log(user_id: str, log: dict[str, Any]) -> None:
    user_logs_dir(user_id).mkdir(parents=True, exist_ok=True)
    with global_history_path(user_id).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(log, handle, sort_keys=False, allow_unicode=False)


def infer_initial_snapshot(current_snapshot: dict[str, Any], user_id: str) -> dict[str, Any]:
    inferred = deepcopy(current_snapshot)
    for name in current_snapshot:
        path = history_path(name, user_id)
        if not path.exists():
            continue
        log = load_history_log(name, user_id)
        if not log["entries"]:
            continue
        first_entry = log["entries"][0]
        if "previous_value" in first_entry:
            inferred[name] = deepcopy(first_entry["previous_value"])
        elif "value" in first_entry:
            inferred[name] = deepcopy(first_entry["value"])
    return inferred


def rebuild_global_history_log(user_id: str) -> dict[str, Any]:
    store = load_store(user_id)
    current_snapshot = snapshot_config_values(store)
    initial_snapshot = infer_initial_snapshot(current_snapshot, user_id)
    profile = load_profile(user_id)
    entries = [
        make_global_history_entry(
            "initial",
            initial_snapshot,
            recorded_at=str(profile.get("created_at") or current_timestamp()),
        )
    ]

    timeline: list[tuple[str, str, int, dict[str, Any]]] = []
    for name in current_snapshot:
        path = history_path(name, user_id)
        if not path.exists():
            continue
        log = load_history_log(name, user_id)
        for index, history_entry in enumerate(log["entries"]):
            if index == 0 and history_entry.get("event") == "initial":
                continue
            timeline.append((str(history_entry.get("recorded_at", "")), name, index, history_entry))

    timeline.sort(key=lambda item: (item[0], item[2], item[1]))
    snapshot = deepcopy(initial_snapshot)
    for recorded_at, name, _, history_entry in timeline:
        previous_value = deepcopy(history_entry.get("previous_value", snapshot.get(name)))
        new_value = deepcopy(history_entry.get("value"))
        snapshot[name] = deepcopy(new_value)
        entries.append(
            make_global_history_entry(
                str(history_entry.get("event", "change")),
                snapshot,
                changed_config=name,
                previous_value=previous_value,
                new_value=new_value,
                recorded_at=recorded_at,
            )
        )

    if entries[-1]["snapshot"] != current_snapshot:
        changed_names = compare_snapshots(entries[-1]["snapshot"], current_snapshot)
        extra_args: dict[str, Any] = {}
        if len(changed_names) == 1:
            changed_name = changed_names[0]
            extra_args["changed_config"] = changed_name
            extra_args["previous_value"] = entries[-1]["snapshot"].get(changed_name)
            extra_args["new_value"] = current_snapshot.get(changed_name)
        elif changed_names:
            extra_args["changed_configs"] = changed_names
        entries.append(make_global_history_entry("sync", current_snapshot, **extra_args))

    log = {"entries": entries}
    save_global_history_log(user_id, log)
    return log


def sync_global_history_log(current_snapshot: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_global_history_log(user_id)
    entries = log["entries"]
    if not entries:
        profile = load_profile(user_id)
        entries.append(
            make_global_history_entry(
                "initial",
                current_snapshot,
                recorded_at=str(profile.get("created_at") or current_timestamp()),
            )
        )
        save_global_history_log(user_id, log)
        return log

    last_snapshot = entries[-1].get("snapshot", {})
    if last_snapshot != current_snapshot:
        changed_names = compare_snapshots(last_snapshot, current_snapshot)
        extra_args: dict[str, Any] = {}
        if len(changed_names) == 1:
            changed_name = changed_names[0]
            extra_args["changed_config"] = changed_name
            extra_args["previous_value"] = last_snapshot.get(changed_name)
            extra_args["new_value"] = current_snapshot.get(changed_name)
        elif changed_names:
            extra_args["changed_configs"] = changed_names
        entries.append(make_global_history_entry("sync", current_snapshot, **extra_args))
        save_global_history_log(user_id, log)

    return log


def append_global_history_entry(entry: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_global_history_log(user_id)
    entry_copy = deepcopy(entry)
    log["entries"].append(entry_copy)
    save_global_history_log(user_id, log)
    return entry_copy


def remove_last_global_history_entry(
    expected: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_global_history_log(user_id)
    entries = log["entries"]
    if len(entries) <= 1:
        raise ValueError("Cannot remove the initial global history entry.")

    last_entry = entries[-1]
    if expected is not None and last_entry != expected:
        raise ValueError("Cannot unlog the global history entry: last entry does not match the expected action.")

    removed = entries.pop()
    save_global_history_log(user_id, log)
    return removed


def global_history_window(
    name: str,
    current_snapshot: dict[str, Any],
    back: int,
    list_count: int,
    user_id: str | None = None,
) -> tuple[list[dict[str, Any]], Path, int]:
    if back < 0:
        raise ValueError("back must be greater than or equal to 0.")
    if list_count < 0:
        raise ValueError("list must be greater than or equal to 0.")

    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = sync_global_history_log(current_snapshot, user_id)
    entries = list(reversed(log["entries"]))
    indexed_entries = [{"back": offset, **entry} for offset, entry in enumerate(entries)]
    if list_count == 0:
        window = indexed_entries[back:]
    else:
        window = indexed_entries[back : back + list_count]
    if not window:
        max_back = len(indexed_entries) - 1
        raise ValueError(f"No global history available for {name} at back={back}. Available range: 0-{max_back}.")
    return window, global_history_path(user_id), len(indexed_entries)


def global_history_changed_label(entry: dict[str, Any]) -> str:
    if entry.get("changed_config"):
        return str(entry["changed_config"])
    if entry.get("changed_configs"):
        return ", ".join(str(name) for name in entry["changed_configs"])
    if entry.get("event") == "initial":
        return "-"
    return ""


def format_global_change(entry: dict[str, Any]) -> str:
    if "previous_value" in entry or "new_value" in entry:
        previous_value = format_value(entry.get("previous_value"))
        new_value = format_value(entry.get("new_value"))
        return f"{previous_value} -> {new_value}"
    if entry.get("event") == "initial":
        return "log initialized"
    if entry.get("changed_configs"):
        return f"{len(entry['changed_configs'])} configs changed"
    return ""


def print_global_history_window(name: str, store: dict[str, Any], back: int, list_count: int) -> None:
    user = get_current_user(required=True)
    assert user is not None
    current_snapshot = snapshot_config_values(store)
    window, log_path, total_entries = global_history_window(name, current_snapshot, back, list_count, user["user_id"])
    relative_log_path = log_path.relative_to(ROOT)
    current_value = current_snapshot[name]
    value_width = max(12, len(name), 22)

    print(f"user: {user['username']}")
    print(f"global history: {name}")
    print(f"current: {format_value(current_value)}")
    print(f"log: {relative_log_path}")
    print(
        f"showing: {len(window)} entr{'y' if len(window) == 1 else 'ies'} "
        f"starting at back={back} (0 is current global state, {total_entries} total)"
    )
    print()
    print(
        f"{'back':>4}  "
        f"{name:<{value_width}} "
        f"{'event':<8} "
        f"{'changed_config':<22} "
        f"{'change':<24} "
        f"{'recorded_at':<25}"
    )
    for history_entry in window:
        snapshot = history_entry.get("snapshot", {})
        print(
            f"{history_entry['back']:>4}  "
            f"{format_value(snapshot.get(name)):<{value_width}} "
            f"{str(history_entry.get('event', '')):<8} "
            f"{global_history_changed_label(history_entry):<22} "
            f"{format_global_change(history_entry):<24} "
            f"{str(history_entry.get('recorded_at', '')):<25}"
        )


def make_history_entry(event: str, value: Any, previous_value: Any | None = None) -> dict[str, Any]:
    entry = {
        "recorded_at": current_timestamp(),
        "event": event,
        "value": deepcopy(value),
    }
    if previous_value is not None:
        entry["previous_value"] = deepcopy(previous_value)
    return entry


def load_history_log(name: str, user_id: str) -> dict[str, Any]:
    path = history_path(name, user_id)
    if not path.exists():
        return {"config": name, "entries": []}

    with path.open("r", encoding="utf-8") as handle:
        log = yaml.safe_load(handle) or {}

    if not isinstance(log, dict):
        raise ValueError(f"{path} must contain a mapping.")

    log_name = log.get("config")
    if log_name not in (None, name):
        raise ValueError(f"{path} is for config '{log_name}', expected '{name}'.")

    entries = log.setdefault("entries", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path} must define 'entries' as a list.")

    log["config"] = name
    return log


def save_history_log(name: str, log: dict[str, Any], user_id: str) -> None:
    user_history_dir(user_id).mkdir(parents=True, exist_ok=True)
    with history_path(name, user_id).open("w", encoding="utf-8") as handle:
        yaml.safe_dump(log, handle, sort_keys=False, allow_unicode=False)


def sync_history_log(name: str, current_value: Any, user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_history_log(name, user_id)
    entries = log["entries"]
    if not entries:
        entries.append(make_history_entry("initial", current_value))
        save_history_log(name, log, user_id)
        return log

    if entries[-1].get("value") != current_value:
        entries.append(make_history_entry("sync", current_value))
        save_history_log(name, log, user_id)
    return log


def append_history_entry(name: str, entry: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_history_log(name, user_id)
    entry_copy = deepcopy(entry)
    log["entries"].append(entry_copy)
    save_history_log(name, log, user_id)
    return entry_copy


def remove_last_history_entry(name: str, expected: dict[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = load_history_log(name, user_id)
    entries = log["entries"]
    if not entries:
        raise ValueError(f"No history exists for {name}.")

    last_entry = entries[-1]
    if expected is not None and last_entry != expected:
        raise ValueError(f"Cannot unlog {name}: last history entry does not match the expected action.")

    removed = entries.pop()
    save_history_log(name, log, user_id)
    return removed


def record_history_change(name: str, old_value: Any, new_value: Any, user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    sync_history_log(name, old_value, user_id)
    if new_value == old_value:
        raise ValueError(f"No history change to record for {name}.")
    return append_history_entry(name, make_history_entry("change", new_value, old_value), user_id)


def history_window(name: str, current_value: Any, back: int, list_count: int, user_id: str | None = None) -> tuple[list[dict[str, Any]], Path, int]:
    if back < 0:
        raise ValueError("back must be greater than or equal to 0.")
    if list_count < 0:
        raise ValueError("list must be greater than or equal to 0.")

    if user_id is None:
        user = get_current_user(required=True)
        assert user is not None
        user_id = str(user["user_id"])

    log = sync_history_log(name, current_value, user_id)
    entries = list(reversed(log["entries"]))
    indexed_entries = [{"back": offset, **entry} for offset, entry in enumerate(entries)]
    if list_count == 0:
        window = indexed_entries[back:]
    else:
        window = indexed_entries[back : back + list_count]
    if not window:
        max_back = len(indexed_entries) - 1
        raise ValueError(f"No history available for {name} at back={back}. Available range: 0-{max_back}.")
    return window, history_path(name, user_id), len(indexed_entries)


def format_history_note(entry: dict[str, Any]) -> str:
    event = str(entry.get("event", ""))
    if event in {"change", "undo", "redo"} and "previous_value" in entry:
        return f"from {format_value(entry['previous_value'])}"
    if event == "initial":
        return "log initialized"
    if event == "sync":
        return "synced with current value"
    return ""


def print_history_window(name: str, entry: dict[str, Any], back: int, list_count: int) -> None:
    user = get_current_user(required=True)
    assert user is not None
    window, log_path, total_entries = history_window(name, entry["value"], back, list_count, user["user_id"])
    relative_log_path = log_path.relative_to(ROOT)

    print(f"user: {user['username']}")
    print(f"history: {name}")
    print(f"current: {format_value(entry['value'])}")
    print(f"log: {relative_log_path}")
    print(f"showing: {len(window)} entr{'y' if len(window) == 1 else 'ies'} starting at back={back} (0 is current, {total_entries} total)")
    print()
    print(f"{'back':>4}  {'value':<22} {'event':<8} {'recorded_at':<25} note")
    for history_entry in window:
        note = format_history_note(history_entry)
        print(
            f"{history_entry['back']:>4}  "
            f"{format_value(history_entry['value']):<22} "
            f"{str(history_entry.get('event', '')):<8} "
            f"{str(history_entry.get('recorded_at', '')):<25} "
            f"{note}"
        )


def parse_cli_bool(raw_value: str) -> bool:
    return parse_bool(raw_value)


def apply_config_change(name: str, updated_value: Any) -> tuple[bool, str]:
    user = get_current_user(required=True)
    assert user is not None
    user_id = str(user["user_id"])
    store = load_store(user_id)
    configs = get_configs(store)
    entry = configs[name]
    old_value = deepcopy(entry["value"])
    old_snapshot = snapshot_config_values(store)

    if updated_value == old_value:
        sync_history_log(name, old_value, user_id)
        sync_global_history_log(old_snapshot, user_id)
        return False, f"No change for {name}; value remains {format_value(old_value)}"

    sync_global_history_log(old_snapshot, user_id)
    entry["value"] = deepcopy(updated_value)
    save_store(store, user_id)
    new_snapshot = snapshot_config_values(store)
    history_entry = record_history_change(name, old_value, updated_value, user_id)
    global_entry = append_global_history_entry(
        make_global_history_entry(
            "change",
            new_snapshot,
            changed_config=name,
            previous_value=old_value,
            new_value=updated_value,
        ),
        user_id,
    )

    session = load_session()
    session["current_user_id"] = user_id
    session["undo_stack"].append(
        {
            "kind": "config_change",
            "recorded_at": current_timestamp(),
            "user_id": user_id,
            "config": name,
            "from_value": old_value,
            "to_value": deepcopy(updated_value),
            "active_log_entry": history_entry,
            "active_global_entry": global_entry,
        }
    )
    session["redo_stack"] = []
    save_session(session)
    return True, f"Updated {name}: {format_value(old_value)} -> {format_value(updated_value)}"


def rename_user_without_action(user_id: str, new_username: str) -> tuple[bool, str, str]:
    return rename_user(user_id, new_username)


def apply_backward_action(session: dict[str, Any], action: dict[str, Any], unlog: bool) -> tuple[dict[str, Any], str]:
    kind = action["kind"]
    redo_record = deepcopy(action)
    redo_record["last_undo"] = {
        "direction": "backward",
        "unlog": unlog,
    }

    if kind == "config_change":
        user_id = str(action["user_id"])
        session["current_user_id"] = user_id
        store = load_store(user_id)
        configs = get_configs(store)
        name = str(action["config"])
        entry = configs[name]
        current_value = entry["value"]
        expected_value = action["to_value"]
        if current_value != expected_value:
            raise ValueError(
                f"Cannot undo {name}: current value is {format_value(current_value)}, expected {format_value(expected_value)}."
            )

        current_snapshot = snapshot_config_values(store)
        sync_global_history_log(current_snapshot, user_id)
        entry["value"] = deepcopy(action["from_value"])
        save_store(store, user_id)
        reverted_snapshot = snapshot_config_values(store)

        if unlog:
            removed_entry = remove_last_history_entry(name, expected=action["active_log_entry"], user_id=user_id)
            removed_global_entry = remove_last_global_history_entry(
                expected=action.get("active_global_entry"),
                user_id=user_id,
            )
            redo_record["last_undo"]["history_entry"] = removed_entry
            redo_record["last_undo"]["global_entry"] = removed_global_entry
        else:
            undo_entry = append_history_entry(
                name,
                make_history_entry("undo", action["from_value"], action["to_value"]),
                user_id,
            )
            undo_global_entry = append_global_history_entry(
                make_global_history_entry(
                    "undo",
                    reverted_snapshot,
                    changed_config=name,
                    previous_value=action["to_value"],
                    new_value=action["from_value"],
                ),
                user_id,
            )
            redo_record["last_undo"]["history_entry"] = undo_entry
            redo_record["last_undo"]["global_entry"] = undo_global_entry

        username = load_profile(user_id)["username"]
        message = f"Undid last change for {username}: {name} {format_value(action['to_value'])} -> {format_value(action['from_value'])}"
        return redo_record, message

    if kind == "user_switch":
        from_user = load_profile(str(action["from_user_id"]))
        to_user = load_profile(str(action["to_user_id"]))
        session["current_user_id"] = from_user["user_id"]
        sync_user_environment_assets(str(from_user["user_id"]))
        message = f"Undid user switch: {to_user['username']} -> {from_user['username']}"
        return redo_record, message

    if kind == "env_mode_change":
        user_id = str(action["user_id"])
        session["current_user_id"] = user_id
        apply_env_state_without_action(user_id, action.get("from_mode"), action.get("from_venv_name"))
        username = load_profile(user_id)["username"]
        from_mode = action.get("to_mode") or "unset"
        to_mode = action.get("from_mode") or "unset"
        from_venv = action.get("to_venv_name") or "none"
        to_venv = action.get("from_venv_name") or "none"
        message = f"Undid env mode for {username}: {from_mode}/{from_venv} -> {to_mode}/{to_venv}"
        return redo_record, message

    if kind == "username_change":
        user_id = str(action["user_id"])
        changed, _, _ = rename_user_without_action(user_id, str(action["from_username"]))
        if not changed:
            raise ValueError("Cannot undo username change because the username is already in the target state.")
        session["current_user_id"] = user_id
        message = f"Undid username change: {action['to_username']} -> {action['from_username']}"
        return redo_record, message

    raise ValueError(f"Unsupported undo action kind: {kind}")


def apply_forward_action(session: dict[str, Any], redo_record: dict[str, Any], unlog: bool) -> tuple[dict[str, Any], str]:
    action = deepcopy(redo_record)
    last_undo = action.pop("last_undo", {})
    kind = action["kind"]

    if kind == "config_change":
        user_id = str(action["user_id"])
        session["current_user_id"] = user_id
        store = load_store(user_id)
        configs = get_configs(store)
        name = str(action["config"])
        entry = configs[name]
        current_value = entry["value"]
        expected_value = action["from_value"]
        if current_value != expected_value:
            raise ValueError(
                f"Cannot replay {name}: current value is {format_value(current_value)}, expected {format_value(expected_value)}."
            )

        current_snapshot = snapshot_config_values(store)
        sync_global_history_log(current_snapshot, user_id)
        entry["value"] = deepcopy(action["to_value"])
        save_store(store, user_id)
        replayed_snapshot = snapshot_config_values(store)

        original_unlog = bool(last_undo.get("unlog"))
        history_entry = last_undo.get("history_entry")
        global_entry = last_undo.get("global_entry")
        if original_unlog:
            if history_entry is None:
                raise ValueError("Redo state is missing the removed history entry.")
            restored_entry = append_history_entry(name, history_entry, user_id)
            action["active_log_entry"] = restored_entry
            if global_entry is None:
                restored_global_entry = append_global_history_entry(
                    make_global_history_entry(
                        "change",
                        replayed_snapshot,
                        changed_config=name,
                        previous_value=action["from_value"],
                        new_value=action["to_value"],
                    ),
                    user_id,
                )
            else:
                restored_global_entry = append_global_history_entry(global_entry, user_id)
            action["active_global_entry"] = restored_global_entry
            note = "restored prior log entry"
        else:
            if history_entry is None:
                raise ValueError("Redo state is missing the undo history entry.")
            if unlog:
                remove_last_history_entry(name, expected=history_entry, user_id=user_id)
                remove_last_global_history_entry(expected=global_entry, user_id=user_id)
                note = "removed undo log entry"
            else:
                redo_entry = append_history_entry(
                    name,
                    make_history_entry("redo", action["to_value"], action["from_value"]),
                    user_id,
                )
                redo_global_entry = append_global_history_entry(
                    make_global_history_entry(
                        "redo",
                        replayed_snapshot,
                        changed_config=name,
                        previous_value=action["from_value"],
                        new_value=action["to_value"],
                    ),
                    user_id,
                )
                action["active_log_entry"] = redo_entry
                action["active_global_entry"] = redo_global_entry
                note = "logged redo entry"

        username = load_profile(user_id)["username"]
        message = f"Replayed change for {username}: {name} {format_value(action['from_value'])} -> {format_value(action['to_value'])} ({note})"
        return action, message

    if kind == "user_switch":
        to_user = load_profile(str(action["to_user_id"]))
        from_user = load_profile(str(action["from_user_id"]))
        session["current_user_id"] = to_user["user_id"]
        sync_user_environment_assets(str(to_user["user_id"]))
        message = f"Replayed user switch: {from_user['username']} -> {to_user['username']}"
        return action, message

    if kind == "env_mode_change":
        user_id = str(action["user_id"])
        session["current_user_id"] = user_id
        apply_env_state_without_action(user_id, action.get("to_mode"), action.get("to_venv_name"))
        username = load_profile(user_id)["username"]
        from_mode = action.get("from_mode") or "unset"
        to_mode = action.get("to_mode") or "unset"
        from_venv = action.get("from_venv_name") or "none"
        to_venv = action.get("to_venv_name") or "none"
        message = f"Replayed env mode for {username}: {from_mode}/{from_venv} -> {to_mode}/{to_venv}"
        return action, message

    if kind == "username_change":
        user_id = str(action["user_id"])
        changed, _, _ = rename_user_without_action(user_id, str(action["to_username"]))
        if not changed:
            raise ValueError("Cannot replay username change because the username is already in the target state.")
        session["current_user_id"] = user_id
        message = f"Replayed username change: {action['from_username']} -> {action['to_username']}"
        return action, message

    raise ValueError(f"Unsupported redo action kind: {kind}")


def apply_undo(direction: str, unlog: bool) -> str:
    session = load_session()
    if direction == "backward":
        if not session["undo_stack"]:
            raise ValueError("No change is available to undo.")
        action = session["undo_stack"].pop()
        redo_record, message = apply_backward_action(session, action, unlog)
        session["redo_stack"].append(redo_record)
        save_session(session)
        return message

    if direction == "forward":
        if not session["redo_stack"]:
            raise ValueError("No undone change is available to replay.")
        redo_record = session["redo_stack"].pop()
        action, message = apply_forward_action(session, redo_record, unlog)
        session["undo_stack"].append(action)
        save_session(session)
        return message

    raise ValueError("dirn must be 'backward' or 'forward'.")
