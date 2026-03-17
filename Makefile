PYTHON ?= python3
.DEFAULT_GOAL := help
SCRIPT_DIR := makescripts
ENV_DIR := .envs
VENV_ROOT := $(ENV_DIR)/venvs
VENV_DIR := $(VENV_ROOT)/make-venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_STAMP := $(VENV_DIR)/.deps_installed
REQUIREMENTS := requirements.txt
CONFIG ?=
VALUE ?=
NAME ?=
ARGS ?=
back ?= 0
list ?= 1
global ?= false
dirn ?= backward
unlog ?= false

POSITIONAL_ROOT_TARGETS := show change new undo remove edit
RECIPE_TARGETS := help show change new undo remove edit status doctor
GOAL_ARG := $(word 2,$(MAKECMDGOALS))
EXTRA_GOALS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
POSITIONAL_ARGS := $(filter-out $(RECIPE_TARGETS),$(EXTRA_GOALS))
CHANGE_VALUE := $(if $(VALUE),$(VALUE),$(NAME))

ifneq ($(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS))),)
ifneq ($(strip $(POSITIONAL_ARGS)),)
$(eval $(POSITIONAL_ARGS):;@:)
endif
endif

SHOW_TARGET := $(if $(CONFIG),$(CONFIG),$(if $(GOAL_ARG),$(if $(filter configs,$(GOAL_ARG)),all,$(GOAL_ARG)),all))
CHANGE_TARGET := $(if $(CONFIG),$(CONFIG),$(GOAL_ARG))
NEW_TARGET := $(if $(GOAL_ARG),$(GOAL_ARG),user)
UNDO_TARGET := $(if $(GOAL_ARG),$(GOAL_ARG),last-change)
REMOVE_TARGET := $(if $(GOAL_ARG),$(GOAL_ARG),user)
EDIT_TARGET := $(if $(CONFIG),$(CONFIG),$(if $(GOAL_ARG),$(GOAL_ARG),venvs))
NEW_PYTHON := $(if $(filter pyvenv,$(NEW_TARGET)),$(PYTHON),$(VENV_PYTHON))
EDIT_PYTHON := $(if $(filter venvs,$(EDIT_TARGET)),$(PYTHON),$(VENV_PYTHON))
REMOVE_PYTHON := $(if $(filter venv,$(REMOVE_TARGET)),$(PYTHON),$(VENV_PYTHON))

.PHONY: help venv show change new undo remove edit status doctor

$(VENV_STAMP): $(REQUIREMENTS)
	@mkdir -p $(VENV_ROOT)
	@test -x $(VENV_PYTHON) || $(PYTHON) -m venv $(VENV_DIR)
	@$(VENV_PYTHON) -m pip install -r $(REQUIREMENTS)
	@touch $(VENV_STAMP)

help:
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then exit 0; fi
	@echo 'Usage:'
	@echo '  make new'
	@echo '    user'
	@echo '      NAME=alice'
	@echo '    pyvenv'
	@echo '      NAME=experiment-a'
	@echo '      ARGS="--python 3.11 --deps-mode none"'
	@echo '      ARGS="--python 3.11 --deps-mode requirements --requirements requirements.txt"'
	@echo '  make show'
	@echo '    configs'
	@echo '    env-mode'
	@echo '    user'
	@echo '    users'
	@echo '    venvs'
	@echo '    <config>'
	@echo '      batch_size'
	@echo '      bn'
	@echo '      CONFIG=lr'
	@echo '      back=5'
	@echo '      list=5'
	@echo '      list=6 back=2'
	@echo '      list=0'
	@echo '      global=true list=0'
	@echo '  make change'
	@echo '    env-mode'
	@echo '      VALUE=interactive'
	@echo '      ARGS="--venv my-venv"'
	@echo '    user'
	@echo '      VALUE=alice'
	@echo '      NAME=alice'
	@echo '    username'
	@echo '      VALUE="New Name"'
	@echo '  make edit'
	@echo '    venvs'
	@echo '      NAME=experiment-a'
	@echo '      ARGS="--install torch==2.5.1 --remove seaborn"'
	@echo '    <config>'
	@echo '      lr'
	@echo '      CONFIG=dropout VALUE=0.2'
	@echo '      ARGS="--config lr --value 0.0005"'
	@echo '  make undo'
	@echo '    last-change'
	@echo '      unlog=true'
	@echo '      dirn=forward'
	@echo '  make remove'
	@echo '    user'
	@echo '      NAME=alice'
	@echo '    venv'
	@echo '  make status'
	@echo '  make doctor'
	@echo ''
	@echo 'Notes:'
	@echo '  The managed make environment is created automatically at .envs/venvs/make-venv.'
	@echo '  Runtime virtual environments are created under .envs/venvs/ by default.'
	@echo '  Active mode files are exposed at configs/ and, for non-interactive mode, slurm/.'
	@echo '  Per-user state lives under state/users/<user>/.'
	@echo '  Raw "make show --config bn" is not valid GNU make syntax.'
	@echo '  Use CONFIG=... or ARGS="--config ..." instead.'

venv: $(VENV_STAMP)

show: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(VENV_PYTHON) $(SCRIPT_DIR)/show.py --config "$(SHOW_TARGET)" --back "$(back)" --list "$(list)" --global "$(global)" $(ARGS)

change: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(VENV_PYTHON) $(SCRIPT_DIR)/change.py $(if $(CHANGE_TARGET),--config "$(CHANGE_TARGET)",) $(if $(CHANGE_VALUE),--value "$(CHANGE_VALUE)",) $(ARGS)

new: $(if $(filter pyvenv,$(NEW_TARGET)),,$(VENV_STAMP))
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	HOST_PYTHON="$(PYTHON)" $(NEW_PYTHON) $(SCRIPT_DIR)/new.py --object "$(NEW_TARGET)" $(if $(NAME),--name "$(NAME)",) $(ARGS)

edit: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	HOST_PYTHON="$(PYTHON)" $(EDIT_PYTHON) $(SCRIPT_DIR)/edit.py --object "$(EDIT_TARGET)" $(if $(NAME),--name "$(NAME)",) $(if $(VALUE),--value "$(VALUE)",) $(ARGS)

undo: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(VENV_PYTHON) $(SCRIPT_DIR)/undo.py --action "$(UNDO_TARGET)" --dirn "$(dirn)" --unlog "$(unlog)" $(ARGS)

status: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(VENV_PYTHON) $(SCRIPT_DIR)/show.py --config "status" $(ARGS)

doctor: $(VENV_STAMP)
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(VENV_PYTHON) $(SCRIPT_DIR)/doctor.py $(ARGS)

remove: $(if $(filter venv,$(REMOVE_TARGET)),,$(VENV_STAMP))
	@if [ "$(filter $(POSITIONAL_ROOT_TARGETS),$(firstword $(MAKECMDGOALS)))" != "" ] && [ "$(firstword $(MAKECMDGOALS))" != "$@" ]; then \
		exit 0; \
	fi; \
	$(REMOVE_PYTHON) $(SCRIPT_DIR)/remove.py --object "$(REMOVE_TARGET)" $(if $(NAME),--name "$(NAME)",) $(ARGS)
