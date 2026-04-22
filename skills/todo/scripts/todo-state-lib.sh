#!/bin/bash
# todo-state-lib.sh — shared state-dir helpers for the /todo background
# worker lifecycle. Sourced by todo-launcher.sh.

# usage: todo_state_init <state_dir>
todo_state_init() {
  mkdir -p "$1"
  touch "$1/audit.log"
}
