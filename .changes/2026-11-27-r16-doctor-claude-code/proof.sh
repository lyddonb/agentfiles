#!/usr/bin/env bash
set -u
REPO=$(pwd)
YAML_PATH=$(python3 -c "import yaml,os;print(os.path.dirname(os.path.dirname(yaml.__file__)))")
S=$(mktemp -d)
mkdir -p "$S/home" "$S/up/skills/alpha" "$S/up/plugins/kit/skills/gamma" "$S/up/plugins/kit/.claude-plugin" "$S/up/.claude-plugin" "$S/repo/profiles"
DESC="Does a thing for the R16 proof. Use when testing the doctor load check."
good() { printf -- "---\nname: alpha\ndescription: $DESC\n---\nBody.\n" > "$S/up/skills/alpha/SKILL.md"; }
printf -- "---\nname: gamma\ndescription: $DESC\n---\nBody.\n" > "$S/up/plugins/kit/skills/gamma/SKILL.md"
echo '{"name":"kit"}' > "$S/up/plugins/kit/.claude-plugin/plugin.json"
echo '{"name":"upstream","owner":{"name":"x"},"plugins":[{"name":"kit","source":"./plugins/kit"}]}' > "$S/up/.claude-plugin/marketplace.json"
printf "sources:\n  up:\n    path: $S/up\n" > "$S/repo/sources.yaml"
printf "targets: [claude-code]\ndefault_profiles: [base]\n" > "$S/repo/agentfiles.yaml"
printf "description: base\nskills:\n  - up:skills/alpha\nplugins:\n  - up:@kit\n" > "$S/repo/profiles/base.yaml"
export PYTHONPATH="$YAML_PATH" HOME="$S/home" AGENTFILES_HOME="$S/repo"
unset XDG_STATE_HOME XDG_DATA_HOME XDG_CACHE_HOME CLAUDE_CONFIG_DIR
af() { "$REPO/bin/agentfiles" "$@"; }
echo "claude $(claude --version 2>/dev/null)"
good; af sync base </dev/null >/dev/null 2>&1; echo "clean sync exit $?"
af doctor 2>&1 | grep -E "load check|loaded|alpha"; echo "clean doctor exit ${PIPESTATUS[0]}"
printf -- "---\nname: alpha\n---\nBody with no description.\n" > "$S/up/skills/alpha/SKILL.md"
af sync base </dev/null >/dev/null 2>&1; echo "broken sync exit $?"
af doctor 2>&1 | grep -E "load check|loaded|alpha"; echo "broken doctor exit ${PIPESTATUS[0]}"
good; af sync base </dev/null >/dev/null 2>&1; echo "fixed sync exit $?"
af doctor 2>&1 | grep -E "load check|loaded|alpha"; echo "fixed doctor exit ${PIPESTATUS[0]}"
echo "session pidfiles left: $(ls "$S/home/.claude/sessions" 2>/dev/null | wc -l | tr -d ' ')"
rm -rf "$S"
