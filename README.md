# jot

Capture mid-development ideas via `/jot <idea>` without losing focus.

A Claude Code plugin that intercepts `/jot` via a `UserPromptSubmit` hook, writes a durable `Todos/<timestamp>_input.txt` file with the idea plus git state and recent conversation context, then spawns a per-invocation background Claude in a shared `jot` tmux session to convert the input into a proper TODO markdown file.

## Status

This repo is being migrated from a split skill+hook system in `matkatmusic/dotfiles`. See `debates/jot-plugin-migration/SYNTHESIS.md` in the dotfiles repo for the migration review, and `~/.claude/plans/dapper-questing-storm.md` for the current plan.

## Requirements

- macOS (uses `osascript` to spawn Terminal.app when no tmux client is attached)
- `tmux`, `jq`, `python3`, `claude` on PATH

## Install

TBD — populated after Phase 1 migration.

## License

MIT
