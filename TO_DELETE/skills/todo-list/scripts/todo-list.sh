#!/bin/bash
# todo-list.sh — function definitions for the /todo-list hook.
# Sourced by todo-list-orchestrator.sh. No side effects when sourced.
#
# Synchronously reads YAML frontmatter from all open TODOs under Todos/
# (excluding Todos/done/) and emits a formatted block via emit_block.

todo_list_main() {
  local REPO
  REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
  export CLAUDE_PLUGIN_ROOT="$REPO"

  . "$REPO/common/scripts/silencers.sh"
  . "$REPO/common/scripts/hook-json.sh"
  . "$REPO/common/scripts/git.sh"

  local INPUT
  INPUT=$(cat)
  case "$INPUT" in
    *'"/todo-list'*) ;;
    *) exit 0 ;;
  esac

  check_requirements "todo-list" jq python3

  local PROMPT
  PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // ""' | \
           python3 "$REPO/common/scripts/jot/strip_stdin.py")
  if [[ "$PROMPT" != "/todo-list" && "$PROMPT" != "/todo-list "* ]]; then
    exit 0
  fi

  local CWD
  CWD=$(printf '%s' "$INPUT" | hide_errors jq -r '.cwd // empty')
  [ -z "$CWD" ] && CWD="$PWD"

  local REPO_ROOT
  REPO_ROOT=$(hide_errors git_get_repo_root "$CWD") || REPO_ROOT=""
  if [ -z "$REPO_ROOT" ]; then
    emit_block "todo-list: not a git repository."
    exit 0
  fi

  if [ ! -d "$REPO_ROOT/Todos" ]; then
    emit_block "No Todos/ folder found in this project."
    exit 0
  fi

  local SCRIPT_DIR FORMATTED
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  FORMATTED=$(TODOS_DIR="$REPO_ROOT/Todos" \
              python3 "$SCRIPT_DIR/format_open_todos.py")

  if [ -z "$FORMATTED" ]; then
    emit_block "No open TODOs."
  else
    emit_block "$FORMATTED"
  fi
  exit 0
}
