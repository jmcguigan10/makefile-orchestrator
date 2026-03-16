from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ENV_DIR = ROOT / ".envs"
VENV_HOME = ENV_DIR / "venvs"
MANAGED_VENV_NAME = "make-venv"
MANAGED_VENV_DIR = VENV_HOME / MANAGED_VENV_NAME
INTERNAL_REQUIREMENTS = ROOT / "requirements.txt"
CANCEL_SENTINEL = "__cancel__"
BACK_SENTINEL = "__back__"

COMMON_LIBRARIES = [
    "numpy",
    "pandas",
    "torch",
    "matplotlib",
    "scikit-learn",
    "scipy",
    "seaborn",
    "jupyter",
    "ipython",
    "pytest",
    "tqdm",
    "transformers",
    "datasets",
]
VERSION_OPERATORS = ("==", "~=", "!=", ">=", "<=", ">", "<")

ANSI_RESET = "\033[0m"
ANSI_RED = "\033[31m"


@dataclass
class MenuChoice:
    label: str
    value: str
    styled_title: Any | None = None


@dataclass
class PyVenvPlan:
    env_dir: Path
    python_command: str
    python_version: str
    dependency_mode: str
    requirements_file: Path | None = None
    packages: list[str] = field(default_factory=list)
    managed_env: bool = False


@dataclass
class VenvInfo:
    name: str
    path: Path
    managed: bool


class OperationCancelled(Exception):
    pass


def load_questionary() -> tuple[Any | None, Any | None]:
    try:
        import questionary  # type: ignore
        from prompt_toolkit.styles import Style  # type: ignore

        return questionary, Style
    except ModuleNotFoundError:
        pass

    lib_dir = MANAGED_VENV_DIR / "lib"
    if not lib_dir.exists():
        return None, None

    for site_packages in sorted(lib_dir.glob("python*/site-packages")):
        if not site_packages.is_dir():
            continue
        if str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))
        try:
            import questionary  # type: ignore
            from prompt_toolkit.styles import Style  # type: ignore

            return questionary, Style
        except ModuleNotFoundError:
            continue

    return None, None


QUESTIONARY, STYLE_CLASS = load_questionary()
QUESTIONARY_STYLE = (
    STYLE_CLASS.from_dict(
        {
            "managed-venv": "fg:#d70000 bold",
            "library-detail": "fg:#6b7280",
            "library-existing": "fg:#005faf bold",
            "library-add": "fg:#2e8b57 bold",
            "library-edit": "fg:#b58900 bold",
            "library-remove": "fg:#d70000 bold",
            "library-missing": "fg:#ffffff",
            "finish": "fg:#005f87 bold",
            "custom-input": "fg:#875f00 bold",
            "warning": "fg:#d70000 bold",
        }
    )
    if STYLE_CLASS is not None
    else None
)


def use_questionary() -> bool:
    return QUESTIONARY is not None and sys.stdin.isatty() and sys.stdout.isatty()


def plain_relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def ansi_red(text: str) -> str:
    return f"{ANSI_RED}{text}{ANSI_RESET}"


def fallback_prompt_text(message: str, default: str | None = None) -> str:
    prompt = message
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    response = input(prompt).strip()
    if response:
        return response
    if default is not None:
        return default
    raise ValueError("No value entered.")


def prompt_text(message: str, default: str | None = None) -> str:
    if use_questionary():
        if default is None:
            response = QUESTIONARY.text(message).ask()
        else:
            response = QUESTIONARY.text(message, default=default).ask()
        if response is None or not response.strip():
            raise ValueError("No value entered.")
        return response.strip()
    return fallback_prompt_text(message, default=default)


def prompt_select(
    message: str,
    choices: list[MenuChoice],
    default: str | None = None,
    *,
    use_shortcuts: bool = True,
    use_search_filter: bool = False,
) -> str:
    if not choices:
        raise ValueError("A non-empty choice list is required.")

    if use_questionary():
        questionary_choices = [
            QUESTIONARY.Choice(title=choice.styled_title or choice.label, value=choice.value) for choice in choices
        ]
        response = QUESTIONARY.select(
            message,
            choices=questionary_choices,
            default=default,
            use_shortcuts=use_shortcuts,
            use_search_filter=use_search_filter,
            use_jk_keys=not use_search_filter,
            style=QUESTIONARY_STYLE,
        ).ask()
        if response is None:
            raise ValueError("Selection cancelled.")
        return response

    print(message)
    for index, choice in enumerate(choices, start=1):
        print(f"  {index}. {choice.label}")
    raw = fallback_prompt_text("Select an option by number or value", default=default)
    if raw.isdigit():
        index = int(raw) - 1
        if index < 0 or index >= len(choices):
            raise ValueError(f"Selection {raw} is out of range.")
        return choices[index].value
    valid_values = {choice.value for choice in choices}
    if raw not in valid_values:
        raise ValueError(f"Unknown selection '{raw}'.")
    return raw


def prompt_confirm(message: str, default: bool = False) -> bool:
    if use_questionary():
        response = QUESTIONARY.confirm(message, default=default, style=QUESTIONARY_STYLE).ask()
        if response is None:
            raise ValueError("Confirmation cancelled.")
        return bool(response)

    default_label = "Y/n" if default else "y/N"
    response = input(f"{message} [{default_label}]: ").strip().lower()
    if not response:
        return default
    return response in {"y", "yes", "true", "1"}


def host_python_command() -> str:
    return os.environ.get("HOST_PYTHON", "python3")


def ensure_venv_home() -> None:
    VENV_HOME.mkdir(parents=True, exist_ok=True)


def split_package_spec(raw: str) -> tuple[str, str | None]:
    cleaned = raw.strip()
    for operator in VERSION_OPERATORS:
        if operator in cleaned:
            name, version = cleaned.split(operator, 1)
            return name.strip(), version.strip()
    return cleaned, None


def package_key(raw: str) -> str:
    name, _ = split_package_spec(raw)
    return name.strip().lower()


def normalize_version_spec(package_name: str, raw_version: str) -> str:
    cleaned = raw_version.strip()
    if not cleaned:
        raise ValueError("Version cannot be empty.")

    if cleaned.startswith(package_name):
        return cleaned

    for operator in VERSION_OPERATORS:
        if cleaned.startswith(operator):
            return f"{package_name}{cleaned}"
    return f"{package_name}=={cleaned}"


def resolve_env_dir(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if candidate.parts and candidate.parts[0] == ".envs":
        return (ROOT / candidate).resolve()
    if len(candidate.parts) == 1:
        ensure_venv_home()
        return (VENV_HOME / candidate).resolve()
    return (ROOT / candidate).resolve()


def find_requirements_files() -> list[Path]:
    excluded_dirs = {".git", ".envs", "state", "__pycache__"}
    results: list[Path] = []
    for path in ROOT.rglob("*.txt"):
        if not path.is_file():
            continue
        if any(part in excluded_dirs for part in path.parts):
            continue
        if "requirements" not in path.name.lower():
            continue
        results.append(path)
    if INTERNAL_REQUIREMENTS.exists():
        results.append(INTERNAL_REQUIREMENTS)
    return sorted(set(results))


def resolve_requirements_file(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    if not candidate.exists():
        raise ValueError(f"Requirements file does not exist: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"Requirements path is not a file: {candidate}")
    return candidate


def resolve_python_interpreter(raw_selection: str | None = None) -> tuple[str, str]:
    if raw_selection is None:
        candidate = host_python_command()
    else:
        cleaned = raw_selection.strip()
        if not cleaned:
            raise ValueError("Python version cannot be empty.")

        expanded = Path(cleaned).expanduser()
        if expanded.exists():
            candidate = str(expanded)
        else:
            possible_commands = [cleaned]
            if re.fullmatch(r"\d+(?:\.\d+){0,2}", cleaned):
                possible_commands.insert(0, f"python{cleaned}")
            resolved = None
            for option in possible_commands:
                resolved = shutil.which(option)
                if resolved:
                    break
            if resolved is None:
                raise ValueError(f"Could not resolve a Python interpreter from '{cleaned}'.")
            candidate = resolved

    process = subprocess.run(
        [candidate, "-c", "import sys; print(sys.version.split()[0])"],
        check=True,
        capture_output=True,
        text=True,
    )
    return candidate, process.stdout.strip()


def prompt_environment_directory(default_dir: str | None = None) -> Path:
    raw_dir = prompt_text("Enter the directory name for the virtual environment", default=default_dir or "my-venv")
    return resolve_env_dir(raw_dir)


def prompt_python_selection() -> tuple[str, str]:
    selection = prompt_select(
        "Choose the Python version to use:",
        [
            MenuChoice("System Python", "system"),
            MenuChoice("Custom Python version", "custom"),
        ],
        default="system",
    )
    if selection == "system":
        return resolve_python_interpreter()

    custom_value = prompt_text("Enter a Python version like 3.11, python3.11, or an interpreter path")
    return resolve_python_interpreter(custom_value)


def prompt_requirements_choice() -> Path:
    existing_files = find_requirements_files()
    if existing_files:
        choices = [MenuChoice(plain_relative(path), str(path)) for path in existing_files]
        choices.append(MenuChoice("Enter a custom requirements path", "__custom__"))
        selected = prompt_select("Select a requirements file:", choices, default=str(existing_files[0]))
        if selected != "__custom__":
            return Path(selected)

    custom_path = prompt_text("Enter the path to a requirements file", default="requirements.txt")
    return resolve_requirements_file(custom_path)


def configure_package_spec(package_name: str, current_spec: str | None = None) -> str | None:
    version_mode = prompt_select(
        f"How should {package_name} be installed?",
        [
            MenuChoice("Latest compatible with selected Python version", "latest"),
            MenuChoice("Custom version", "custom"),
            MenuChoice("Back", BACK_SENTINEL),
        ],
        default="latest",
    )
    if version_mode == BACK_SENTINEL:
        return None
    if version_mode == "latest":
        return package_name

    default_version = None
    if current_spec:
        _, version = split_package_spec(current_spec)
        default_version = version
    raw_version = prompt_text(
        f"Enter the version for {package_name} (for example 2.3.1 or {package_name}==2.3.1)",
        default=default_version,
    )
    return normalize_version_spec(package_name, raw_version)


def prompt_custom_library() -> tuple[str, str | None]:
    raw = prompt_text("Enter the library name or a full pip spec")
    name, version = split_package_spec(raw)
    if not name:
        raise ValueError("Library name cannot be empty.")
    if version is not None:
        operator_match = next((operator for operator in VERSION_OPERATORS if operator in raw), "==")
        return name, f"{name}{operator_match}{version}"
    return name, configure_package_spec(name)


def venv_python_path(env_dir: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return env_dir / scripts_dir / executable


def is_venv_dir(path: Path) -> bool:
    return path.is_dir() and (path / "pyvenv.cfg").exists() and venv_python_path(path).exists()


def ensure_target_ready(env_dir: Path) -> None:
    if env_dir.exists():
        if env_dir.is_file():
            raise ValueError(f"Target path already exists as a file: {env_dir}")
        if any(env_dir.iterdir()):
            should_replace = prompt_confirm(
                f"{plain_relative(env_dir)} already exists and is not empty. Replace it?",
                default=False,
            )
            if not should_replace:
                raise ValueError("Environment creation cancelled.")
            shutil.rmtree(env_dir)
        else:
            env_dir.rmdir()


def run_command(command: list[str], description: str) -> None:
    print(description)
    subprocess.run(command, check=True)


def install_packages(plan: PyVenvPlan, env_python: Path) -> None:
    run_command([str(env_python), "-m", "pip", "install", "--upgrade", "pip"], "Upgrading pip...")

    installed_requirements: set[Path] = set()
    managed_requirements = INTERNAL_REQUIREMENTS.resolve()
    if plan.managed_env:
        run_command(
            [str(env_python), "-m", "pip", "install", "-r", str(INTERNAL_REQUIREMENTS)],
            f"Installing managed make dependencies from {plain_relative(INTERNAL_REQUIREMENTS)}...",
        )
        installed_requirements.add(managed_requirements)

    if plan.requirements_file is not None:
        resolved_requirements = plan.requirements_file.resolve()
        if resolved_requirements not in installed_requirements:
            run_command(
                [str(env_python), "-m", "pip", "install", "-r", str(plan.requirements_file)],
                f"Installing dependencies from {plain_relative(plan.requirements_file)}...",
            )
            installed_requirements.add(resolved_requirements)

    if plan.packages:
        run_command(
            [str(env_python), "-m", "pip", "install", *plan.packages],
            "Installing selected libraries: " + ", ".join(plan.packages),
        )


def create_virtualenv(plan: PyVenvPlan) -> None:
    ensure_venv_home()
    ensure_target_ready(plan.env_dir)

    if plan.managed_env:
        print("Managed make environment selected; tooling dependencies will be preserved.")

    run_command(
        [plan.python_command, "-m", "venv", str(plan.env_dir)],
        (
            f"Creating virtual environment at {plain_relative(plan.env_dir)} "
            f"using Python {plan.python_version} ({plan.python_command})..."
        ),
    )

    env_python = venv_python_path(plan.env_dir)
    if not env_python.exists():
        raise ValueError(f"New virtual environment is missing its Python executable: {env_python}")

    install_packages(plan, env_python)
    print(f"Virtual environment ready: {plain_relative(plan.env_dir)}")


def list_virtualenvs() -> list[VenvInfo]:
    ensure_venv_home()
    venvs: list[VenvInfo] = []
    for child in VENV_HOME.iterdir():
        if not is_venv_dir(child):
            continue
        venvs.append(VenvInfo(name=child.name, path=child, managed=child.resolve() == MANAGED_VENV_DIR.resolve()))
    venvs.sort(key=lambda item: (0 if item.managed else 1, item.name.lower()))
    return venvs


def get_venv_by_name(name: str) -> VenvInfo:
    normalized = name.strip().lower()
    for info in list_virtualenvs():
        if info.name.lower() == normalized:
            return info
    known = ", ".join(info.name for info in list_virtualenvs())
    raise ValueError(f"Unknown virtual environment '{name}'. Known venvs: {known}")


def prompt_for_venv(message: str = "Select a virtual environment to edit:") -> VenvInfo:
    venvs = list_virtualenvs()
    if not venvs:
        raise ValueError("No virtual environments exist yet. Run 'make new pyvenv' first.")

    choices: list[MenuChoice] = []
    for info in venvs:
        if info.managed:
            choices.append(
                MenuChoice(
                    f"{info.name} (managed)",
                    info.name,
                    styled_title=[("class:managed-venv", f"{info.name} (managed)")],
                )
            )
        else:
            choices.append(MenuChoice(info.name, info.name))
    selected = prompt_select(message, choices, use_shortcuts=True)
    return get_venv_by_name(selected)


def get_installed_packages(env_dir: Path) -> list[dict[str, str]]:
    env_python = venv_python_path(env_dir)
    process = subprocess.run(
        [str(env_python), "-m", "pip", "list", "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    )
    packages = json.loads(process.stdout or "[]")
    if not isinstance(packages, list):
        raise ValueError(f"Unexpected package list output for {env_dir}.")
    normalized: list[dict[str, str]] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = str(package.get("name", "")).strip()
        version = str(package.get("version", "")).strip()
        if not name:
            continue
        normalized.append({"name": name, "version": version})
    normalized.sort(key=lambda package: package["name"].lower())
    return normalized


def installed_package_map(env_dir: Path) -> dict[str, dict[str, str]]:
    return {package_key(package["name"]): package for package in get_installed_packages(env_dir)}


def apply_package_changes(
    env_dir: Path,
    *,
    remove_packages: list[str],
    install_specs: list[str],
) -> None:
    env_python = venv_python_path(env_dir)
    if remove_packages:
        run_command(
            [str(env_python), "-m", "pip", "uninstall", "-y", *remove_packages],
            "Removing libraries: " + ", ".join(remove_packages),
        )
    if install_specs:
        run_command(
            [str(env_python), "-m", "pip", "install", *install_specs],
            "Installing libraries: " + ", ".join(install_specs),
        )
