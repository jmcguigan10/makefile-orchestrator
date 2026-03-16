# makefile-orchestrator

`makefile-orchestrator` is a small Make-driven control plane for ML experiment setup.

The main idea is:

- keep mutable experiment state out of source files
- give each user their own config and log state without using Git branches
- make common state changes scriptable from `make`
- support both local interactive runs and non-interactive HPC or Slurm-style submission

## Why this exists

Typical ML projects end up with a few recurring problems:

- config files are edited manually and drift over time
- one person's "current config" collides with someone else's
- experiment history is hard to inspect
- HPC submission wants generated config and launcher files, while local iteration wants something simpler

This repo treats `make` as the operator interface for those problems. The Makefile delegates all real work to Python scripts in [`makescripts/`](makescripts), so each command stays focused and scriptable.

## Core model

- Per-user config state lives under `state/users/<user>/`.
- Per-config history logs also live under `state/users/<user>/`.
- Runtime virtual environments live under `.envs/venvs/`.
- The special tooling environment is `.envs/venvs/make-venv`.
- Hidden generated mode assets live under:
  - `.envs/configs/<user>/<mode>/`
  - `.envs/slurm/<user>/<mode>/`
- Active root views are exposed through:
  - `configs/`
  - `slurm/`

When `env-mode` is set:

- `interactive` exposes only `configs/`
- `non-interactive` exposes both `configs/` and `slurm/`

Those root paths are generated views, not the source of truth.

## Command overview

Running `make` with no target shows help.

### `make new`

Create new stateful objects.

#### `make new user`

Creates a user, initializes that user's config state from [`mlp_configs.yaml`](mlp_configs.yaml), creates log storage, and makes that user current.

Examples:

```bash
make new user
make new user NAME=alice
```

#### `make new pyvenv`

Creates a runtime Python virtual environment under `.envs/venvs/` by default.

The flow supports:

- system Python or a custom interpreter
- installing from a requirements file
- selecting libraries interactively
- configuring versions per library

Examples:

```bash
make new pyvenv
make new pyvenv NAME=experiment-a
```

### `make show`

Read current state without mutating it.

#### `make show configs`

Shows the full current config table for the active user.

```bash
make show configs
make show
```

#### `make show <config>`

Shows one config in detail.

```bash
make show bn
make show batch_size
make show CONFIG=lr
```

#### Config history window options

You can inspect per-config history using `back` and `list`.

- `back=N` starts N steps back from the current entry
- `list=M` shows M entries starting from that offset
- `list=0` means "show everything from `back` onward"

Examples:

```bash
make show batch_size back=5
make show batch_size list=5
make show batch_size list=6 back=2
make show batch_size list=0
```

#### Global config-state history

`global=true` switches from the local per-config log to the full config-state timeline.

This is useful when you want to see how one config looked across all experiment state changes, even when some other config changed.

Example:

```bash
make show seed global=true list=0
```

#### `make show user`

Shows the current active user.

```bash
make show user
```

#### `make show env-mode`

Shows the current execution mode for the active user, the selected venv, and where the active and hidden generated files live.

```bash
make show env-mode
```

#### `make show venvs`

Lists all known virtual environments and their installed libraries.

`make-venv` is highlighted specially because it is the internal tooling environment.

```bash
make show venvs
```

### `make change`

Change user-level state.

This command is intentionally narrow now. Config value edits live under `make edit`.

#### `make change user`

Switches the active user.

Examples:

```bash
make change user
make change user VALUE=alice
```

#### `make change username`

Renames the current user.

Examples:

```bash
make change username
make change username VALUE="Alice Smith"
```

#### `make change env-mode`

Switches between local interactive and non-interactive submission mode.

The command prompts for:

- mode: `interactive` or `non-interactive`
- which venv should be associated with that mode

Examples:

```bash
make change env-mode
make change env-mode VALUE=interactive ARGS="--venv my-venv"
make change env-mode VALUE=non-interactive ARGS="--venv my-venv"
```

When mode changes:

- hidden generated assets are refreshed under `.envs/`
- `configs/` is pointed at the active mode's generated config set
- `slurm/` is exposed only for `non-interactive`

For `non-interactive`, the generated files currently include:

- `configs/train_example.yaml`
- `configs/environment.yaml`
- `configs/slurm_job.yaml`
- `slurm/submit.sh`

### `make edit`

Edit mutable experiment objects.

#### `make edit <config>`

Edits one config value for the active user.

- choice and bool values use selection prompts
- numeric and list values accept typed input

Examples:

```bash
make edit lr
make edit bn VALUE=false
make edit CONFIG=dropout VALUE=0.2
make edit ARGS="--config lr --value 0.0005"
```

Each config edit updates:

- the user's current config state
- the per-config history log
- the global config-state history
- generated mode assets under `.envs/`

#### `make edit venvs`

Edits installed libraries inside a chosen runtime venv.

Examples:

```bash
make edit venvs
make edit venvs NAME=experiment-a
```

Behavior:

- existing libraries are shown in blue
- staged add, edit, and remove actions are color-coded
- `make-venv` requires an explicit confirmation prompt before editing

### `make undo`

Undo or replay the last change-oriented action.

Supported actions currently include:

- config edits
- user switches
- username changes
- env-mode changes

#### Undo the most recent change

```bash
make undo last-change
```

#### Replay the most recent undo

```bash
make undo last-change dirn=forward
```

#### `unlog=true`

Controls whether undo/redo should remove the related log entry instead of appending a compensating `undo` or `redo` entry.

Examples:

```bash
make undo last-change unlog=true
make undo last-change dirn=forward unlog=true
```

### `make remove`

Remove local managed state.

#### `make remove user`

Deletes a selected user's state.

Examples:

```bash
make remove user
make remove user NAME=alice
```

#### `make remove venv`

Removes the managed tooling environment at `.envs/venvs/make-venv`.

This is mostly a maintenance command.

```bash
make remove venv
```

### Internal target: `make venv`

`make venv` bootstraps the managed tooling environment used by the Makefile scripts.

In normal use this is automatic because most commands depend on it, so it is intentionally not emphasized in the help output.

```bash
make venv
```

## Make syntax note

Raw GNU Make syntax like this does not work:

```bash
make show --config bn
```

Use one of these patterns instead:

```bash
make show bn
make show CONFIG=bn
make show ARGS="--config bn"
```

The same rule applies to other commands that forward CLI flags to Python scripts.

## Typical workflow

### First-time setup

```bash
make new user NAME=alice
make new pyvenv NAME=experiment-a
make change env-mode VALUE=interactive ARGS="--venv experiment-a"
```

### Local iteration

```bash
make edit lr VALUE=0.0003
make edit batch_size VALUE=256
make show configs
make show lr list=5
```

### Switch to non-interactive submission mode

```bash
make change env-mode VALUE=non-interactive ARGS="--venv experiment-a"
make show env-mode
```

At that point:

- `configs/` points at the generated active config view
- `slurm/` points at the generated submission view

### Roll back a bad change

```bash
make undo last-change
make undo last-change dirn=forward
```

## Repository layout

Source files:

- [`Makefile`](Makefile)
- [`mlp_configs.yaml`](mlp_configs.yaml)
- [`makescripts/`](makescripts)

Generated or local state:

- `.envs/`
- `state/`
- active `configs/`
- active `slurm/`

## Current scope

This project is a local orchestration layer, not a full experiment runner.

It currently focuses on:

- user-scoped config state
- config history and global history inspection
- venv lifecycle management
- active mode materialization for local vs. non-interactive execution
- a generated Slurm submission skeleton
