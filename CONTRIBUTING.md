# Contributing to testkit

Thanks for helping. This guide covers how the repository is organised, the rules that keep the kit working across coding agents, and how to send a change.

## Repository layout

| Path | What it is |
|---|---|
| `agents/*.md` | The four role agents (source of truth). `bin/testkit_sync.py` generates Codex TOML, Cursor, Gemini and Copilot files from them. |
| `skills/<name>/` | Skills in the [Agent Skills](https://agentskills.io/specification) format: `SKILL.md` plus optional `scripts/`, `references/`, `assets/`. |
| `skills/docx`, `pdf`, `xlsx`, `pptx` | Vendored third-party skills. Do not edit; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). |
| `templates/qa/config.yml` | The project config that `testkit init` creates. |
| `bin/testkit`, `bin/testkit.ps1` | The `testkit` CLI (fetch kit, init/update, doctor). |
| `bin/testkit_sync.py` | Installs skills and agents into a project for each coding agent. |
| `install.sh`, `install.ps1` | One-line installers. |
| `scripts/build-site.sh`, `vercel.json` | Builds the static install site (`public/`). |
| `scripts/check-kit.py` | Static checks; CI runs it. |
| `docs/` | Detailed documentation. |

## Development setup

```bash
git clone https://github.com/ethantrannn/testkit && cd testkit
./install.sh --skip-prereqs          # installs the testkit command from this checkout
cd /path/to/a/test/project
TESTKIT_SOURCE=/path/to/testkit testkit init --agents all
```

`testkit init` copies the kit into the project, so after each edit run `testkit update` in the test project to pick up your change.

## Rules for skills and agents

1. **Follow the Agent Skills spec.** The folder name equals `name` (lowercase letters, digits, single hyphens). `description` is 1024 characters or less and says what the skill does and when to use it. Keep `SKILL.md` under 500 lines; move details into `references/`.
2. **Stay portable.** Skills run in Claude Code, Codex, Cursor, Gemini CLI and Copilot.
   - Do not name tool-specific tools (no "Skill tool", "Read tool", "Agent tool"). Refer to other skills by name.
   - Resolve script paths with `SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)`.
   - Run commands from the project root.
3. **Scripts.**
   - Python runs with `uv run` and PEP 723 inline metadata, with pinned dependency versions.
   - Bash must also work in Git Bash on Windows.
   - Every script prints usage, fails with a clear message and a non-zero exit code.
4. **Config and secrets.** New settings go into `templates/qa/config.yml` with comments. Secrets are referenced by environment variable name, never stored.
5. **Safety first.**
   - Only touch environments listed in the config, and respect `allow_write: false`.
   - Database access is read-only.
   - Run load and security tooling only where the config allows it, never on production.
   - Ask the user before anything billed or outward-facing.
6. **Outputs** go under `qa/`. Human-facing text follows `project.language`; IDs, statuses and field names stay in English.

## Translations

`README.md` is the source. When you change it, update `README.vi.md`, `README.zh-CN.md`, `README.ja.md` and `README.ko.md`, or note in the pull request which ones still need updating. To add a language, create `README.<lang>.md` and add it to the language bar at the top of every README. `scripts/check-kit.py` checks that the bars link to each other.

## Before you open a pull request

```bash
python3 scripts/check-kit.py         # skills spec, portability, syntax, install for every agent, README links
```

Then:

- Test what you changed for real: run the script, or run the skill in at least one coding agent against a sample project. Describe what you ran in the pull request.
- Keep pull requests focused: one skill or one fix per pull request.
- Bump `version` in `.claude-plugin/plugin.json` for user-visible changes, following semantic versioning.

## Reporting bugs and ideas

Open an issue with:

- the coding agent and its version;
- your OS;
- the output of `testkit doctor`;
- what you expected and what happened.

For security problems, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
