expand_permissions.py: loads permissions.local.json, applies the legacy `Todos/` migration shim, expands `${CWD}` / `${HOME}` / `${REPO_ROOT}` in each rule, and prints the resulting JSON array to stdout
render_template.py: expands `${VAR}` placeholders in a template file from env vars and fails loud if any placeholder survives
strip_stdin.py: reads stdin and prints it with leading/trailing whitespace stripped
