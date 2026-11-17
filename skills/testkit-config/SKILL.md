---
name: testkit-config
description: Fill in or update qa/config.yml for testkit — environments and base URLs, docs/code paths, test-account strategy, roles, tracker, language — by detecting what it can from the project and asking only for the rest. Use right after `testkit init`, when the user says "configure testkit", "setup QA", or when another testkit skill finds qa/config.yml missing or still holding example values.
---

# testkit config

`testkit init` (the terminal command) already installed the skills and role agents for the project's coding agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot) and created the `qa/` skeleton with an example `qa/config.yml`. Your job is to make that config true for this project.

## Steps

1. Read `qa/config.yml`. If it does not exist, tell the user to run `testkit init` in the project folder first and stop.
2. Detect, then fill:
   - `docs.paths`, `code.paths`: existing folders such as `docs/`, `src/`, `app/`, `apps/*`, `packages/*`, `server/`. Include folders holding Word specs (`*.docx`); agents convert them with pandoc.
   - `report.formats`: add `docx` if the team sends reports to people outside the repo (check that `pandoc` is installed; `testkit doctor` shows it).
   - `environments.local.base_url`: the dev server port from `package.json` scripts, framework config, `docker-compose.yml`, or `.env*` keys like `APP_URL`, `NEXT_PUBLIC_*_URL`, `VITE_*_URL`.
   - `accounts.roles`: role enums or permission constants in the code.
   - `accounts.strategy`: `command` if there is a seed script that creates users, `api` if there is a test-user endpoint, otherwise `signup`.
   - `project.language`: the language the user is writing in.
3. Ask the user, one question at a time, only for what you could not detect: the staging URL, whether staging allows writes, the email/OTP inbox if sign-up needs verification, and whether bugs go to Jira.
4. Remove example values that do not apply (for example the `staging` block if the project has no staging). Keep comments that explain options.
5. Browser: keep `browser.tool: browser-use` and `browser.mode: isolated` unless the user needs otherwise. Use `local` only when tests need the user's own Chrome logins (for example corporate SSO); it runs one stream at a time. Use `cloud` only if the user has a Browser Use account and accepts the cost. Check the CLI with `browser-use --version` (needs 1.x); if missing, tell the user to run `testkit doctor` in the terminal.
6. Knowledge: run `testkit graph detect` in the terminal (or ask the user to) to see whether a Graphiti knowledge graph is available. If one is found, set `knowledge.graphiti.url` and ask the user once whether project text may be sent to that graph's LLM provider (`knowledge.graphiti.consent: granted | denied`); if not, explain that knowledge stays in `qa/knowledge/` files and that `testkit graph up` starts a graph (Docker, and an LLM API key whose provider will receive the ingested text). Then offer `testkit-knowledge learn` to build the project map.
7. Show the final config and the next command: `/testkit-run <ticket>`.
