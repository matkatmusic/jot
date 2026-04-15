#!/usr/bin/env python3
# expand_permissions.py — load a plugin permissions.local.json file, apply
# the legacy-form migration shim, expand ${CWD}/${HOME}/${REPO_ROOT} template
# placeholders in each `permissions.allow` entry, and print the resulting
# JSON array to stdout.
#
# Inputs:
#   sys.argv[1] (or $PERMISSIONS_FILE) — path to the permissions JSON file.
#   $CWD, $HOME, $REPO_ROOT — template values. $REPO_ROOT is used with its
#     leading "/" stripped so the output slots into a "//${REPO_ROOT}/..." form.
#
# Side effects:
#   If the on-disk file contains any legacy cwd-relative rule starting with
#   "Write(Todos/" or "Edit(Todos/", a one-line warning is written to stderr
#   and absolute "//${REPO_ROOT}/Todos/**" rules are injected into the
#   in-memory allow array. The on-disk file is never modified.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md
# (commit 2). Behavior is identical to the previous inline block.
import json
import os
import sys

path = os.environ.get("PERMISSIONS_FILE") or sys.argv[1]
with open(path) as f:
    data = json.load(f)
allow = data.get("permissions", {}).get("allow", [])
repo_root = os.environ["REPO_ROOT"].lstrip("/")

# ── Backward-compat migration shim (in-memory, non-destructive) ──────
# Existing installs may have edited permissions.local.json with the
# legacy cwd-relative form Write(Todos/**)/Edit(Todos/**). Post-upgrade
# the worker emits absolute tool args, which never match cwd-relative
# patterns when the worker cwd is a subdirectory of the repo root.
# Without this shim every Write would silently deny on first /jot.
#
# Strategy: detect legacy entries, auto-inject the absolute //${REPO_ROOT}
# rules into the in-memory allow array, and warn the user on stderr.
# We do NOT mutate the on-disk file — that would clobber custom
# formatting and other user edits the user is entitled to keep.
LEGACY_PATTERNS = ("Write(Todos/", "Edit(Todos/")
has_legacy = any(item.startswith(LEGACY_PATTERNS) for item in allow)
required = [
    "Write(//${REPO_ROOT}/Todos/**)",
    "Edit(//${REPO_ROOT}/Todos/**)",
]
for rule in required:
    if rule not in allow:
        allow.append(rule)
if has_legacy:
    sys.stderr.write(
        "[jot] WARN: legacy cwd-relative Write(Todos/**)/Edit(Todos/**) "
        "rules detected in permissions.local.json. Auto-granting absolute "
        "Write/Edit access to ${REPO_ROOT}/Todos/. Update your local file "
        "to silence this warning.\n"
    )

expanded = [
    item
      .replace("${CWD}", os.environ["CWD"])
      .replace("${HOME}", os.environ["HOME"])
      .replace("${REPO_ROOT}", repo_root)
    for item in allow
]
print(json.dumps(expanded))
