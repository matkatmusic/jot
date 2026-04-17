#!/bin/bash
# git.sh — git query functions.

source "$(dirname "${BASH_SOURCE[0]}")/invoke_command.sh"

# ========================================================
# usage: git_is_repo <directory>
# returns: 0 if directory is inside a git work tree, 1 if not
git_is_repo() {
  hide_output hide_errors git -C "$1" rev-parse --is-inside-work-tree
  local result=$?
  return $result
}

# usage: git_get_repo_root [directory]
# returns: 0 on success (prints absolute repo root path), 1 if not in a git repo
git_get_repo_root() {
  local dir="${1:-.}"
  local git_common_dir
  git_common_dir="$(hide_errors git -C "$dir" rev-parse --git-common-dir)"
  local result=$?
  if [ $result -ne 0 ]; then
    echo "[git] not inside a git repository" >&2
    return 1
  fi
  (cd "$dir" && cd "$(dirname "$git_common_dir")" && pwd)
}

# usage: git_get_branch_name <directory>
# returns: 0 on success (prints branch name), 1 if not a git repo or detached HEAD
git_get_branch_name() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local branch
  branch=$(hide_errors git -C "$1" branch --show-current)
  if [ -z "$branch" ]; then
    echo "HEAD detached at $(hide_errors git -C "$1" rev-parse --short HEAD)" >&2
    return 1
  fi
  echo "$branch"
}

# usage: git_get_recent_commits <directory>
# returns: 0 on success (prints space-separated hashes), 1 if not a git repo or no commits
git_get_recent_commits() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local commits
  commits=$(hide_errors git -C "$1" log --oneline -5 --format='%h' | tr '\n' ' ' | sed 's/ $//')
  if [ -z "$commits" ]; then
    echo "No commits yet" >&2
    return 1
  fi
  echo "$commits"
}

# usage: git_get_uncommitted <directory>
# returns: 0 on success (prints space-separated filenames), 1 if not a git repo
# prints "None" and returns 0 if the working tree is clean
git_get_uncommitted() {
  if ! git_is_repo "$1"; then
    echo "[git] not a git repository: $1" >&2
    return 1
  fi
  local uncommitted
  uncommitted=$(hide_errors git -C "$1" status --short | awk '{print $2}' | tr '\n' ' ' | sed 's/ $//')
  if [ -z "$uncommitted" ]; then
    echo "None"
    return 0
  fi
  echo "$uncommitted"
}

# usage: git_ensure_gitignore_entry <repo_root> <pattern>
# returns: 0 on success, 1 if not a git repo
# Appends <pattern> to .gitignore if not already present.
git_ensure_gitignore_entry() {
  local gitignore="$1/.gitignore"
  if ! hide_errors grep -qxF "$2" "$gitignore"; then
    printf '\n%s\n' "$2" >> "$gitignore"
  fi
}

# ========================================================
git_tests() {
  local test_dir pass=0 fail=0

  # ── git_is_repo ──
  test_dir=$(mktemp -d)
  git -C "$test_dir" init -q
  if git_is_repo "$test_dir"; then
    echo "PASS: git_is_repo true for repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_is_repo false for repo"
    fail=$((fail + 1))
  fi
  if ! git_is_repo /tmp; then
    echo "PASS: git_is_repo false for non-repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_is_repo true for non-repo"
    fail=$((fail + 1))
  fi

  # ── git_get_repo_root ──
  local root
  root=$(git_get_repo_root "$test_dir" 2>/dev/null)
  if [ $? -eq 0 ] && [ "$root" = "$test_dir" ]; then
    echo "PASS: git_get_repo_root returns correct path"
    pass=$((pass + 1))
  else
    echo "FAIL: expected '$test_dir', got '$root'"
    fail=$((fail + 1))
  fi
  if ! git_get_repo_root /tmp 2>/dev/null; then
    echo "PASS: git_get_repo_root fails for non-repo"
    pass=$((pass + 1))
  else
    echo "FAIL: git_get_repo_root should fail for non-repo"
    fail=$((fail + 1))
  fi

  # ── git_get_branch_name ──
  git -C "$test_dir" checkout -b test-branch-$$ -q 2>/dev/null
  git -C "$test_dir" commit --allow-empty -m "init" -q
  local branch
  branch=$(git_get_branch_name "$test_dir" 2>/dev/null)
  if [ $? -eq 0 ] && [ "$branch" = "test-branch-$$" ]; then
    echo "PASS: git_get_branch_name returns branch"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'test-branch-$$', got '$branch'"
    fail=$((fail + 1))
  fi
  git -C "$test_dir" checkout --detach -q 2>/dev/null
  if ! git_get_branch_name "$test_dir" 2>/dev/null; then
    echo "PASS: git_get_branch_name fails on detached HEAD"
    pass=$((pass + 1))
  else
    echo "FAIL: should fail on detached HEAD"
    fail=$((fail + 1))
  fi
  git -C "$test_dir" checkout test-branch-$$ -q 2>/dev/null

  # ── git_get_recent_commits ──
  git -C "$test_dir" commit --allow-empty -m "second" -q
  local commits
  commits=$(git_get_recent_commits "$test_dir" 2>/dev/null)
  local count
  count=$(echo "$commits" | wc -w | tr -d ' ')
  if [ $? -eq 0 ] && [ "$count" -eq 2 ]; then
    echo "PASS: git_get_recent_commits returns 2 hashes"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 2 hashes, got $count"
    fail=$((fail + 1))
  fi

  # ── git_get_uncommitted ──
  local uncommitted
  uncommitted=$(git_get_uncommitted "$test_dir" 2>/dev/null)
  if [ "$uncommitted" = "None" ]; then
    echo "PASS: git_get_uncommitted clean repo returns 'None'"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'None', got '$uncommitted'"
    fail=$((fail + 1))
  fi
  echo "dirty" > "$test_dir/changed.txt"
  uncommitted=$(git_get_uncommitted "$test_dir" 2>/dev/null)
  if echo "$uncommitted" | grep -qF 'changed.txt'; then
    echo "PASS: git_get_uncommitted lists changed file"
    pass=$((pass + 1))
  else
    echo "FAIL: expected 'changed.txt', got '$uncommitted'"
    fail=$((fail + 1))
  fi

  # ── git_ensure_gitignore_entry ──
  git_ensure_gitignore_entry "$test_dir" ".plate/"
  if grep -qxF '.plate/' "$test_dir/.gitignore"; then
    echo "PASS: git_ensure_gitignore_entry adds entry"
    pass=$((pass + 1))
  else
    echo "FAIL: entry not found in .gitignore"
    fail=$((fail + 1))
  fi
  git_ensure_gitignore_entry "$test_dir" ".plate/"
  local entry_count
  entry_count=$(grep -cxF '.plate/' "$test_dir/.gitignore")
  if [ "$entry_count" -eq 1 ]; then
    echo "PASS: git_ensure_gitignore_entry is idempotent"
    pass=$((pass + 1))
  else
    echo "FAIL: duplicate entries ($entry_count)"
    fail=$((fail + 1))
  fi

  rm -rf "$test_dir"
  printf "git_tests: PASS=%d FAIL=%d\n" "$pass" "$fail"
  [ "$fail" -eq 0 ]
}
