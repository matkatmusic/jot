#!/usr/bin/env python3
# render_template.py — expand ${VAR} placeholders in a template file.
#
# Usage:
#   python3 render_template.py <template_path> VAR1 [VAR2 ...]
#
# Each named variable is read from the process environment and substituted
# for every `${VAR}` occurrence in the template. After substitution, the
# file is scanned for any remaining `${IDENT}` tokens; if any are found,
# the script exits non-zero with a loud error on stderr. This ensures
# missing template inputs fail fast instead of silently shipping literal
# `${FOO}` text to a downstream consumer.
#
# Extracted from scripts/jot.sh per plans/jot-generalizing-refactor.md (commit 5).
import os
import re
import sys

if len(sys.argv) < 3:
    sys.stderr.write("render_template.py: usage: render_template.py <template> VAR [VAR...]\n")
    sys.exit(2)

template_path = sys.argv[1]
expected_vars = sys.argv[2:]

with open(template_path) as f:
    text = f.read()

for var in expected_vars:
    value = os.environ.get(var)
    if value is None:
        sys.stderr.write(f"render_template.py: env var {var} is not set\n")
        sys.exit(2)
    text = text.replace("${" + var + "}", value)

# Fail loud if any ${IDENT} token survived — missing template inputs should
# be noisy, not silent.
leftover = re.findall(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", text)
if leftover:
    sys.stderr.write(
        f"render_template.py: unexpanded placeholders in {template_path}: "
        f"{sorted(set(leftover))}\n"
    )
    sys.exit(2)

sys.stdout.write(text)
