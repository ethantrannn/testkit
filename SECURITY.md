# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately with GitHub's **Report a vulnerability** button, under the repository's **Security** tab (private security advisory). Include:

- what is affected (installer, `testkit` CLI, a skill or script, the install site);
- steps to reproduce, or a proof of concept;
- the impact you expect.

We aim to acknowledge reports within 3 working days and to agree on a fix and disclosure date with you.

## Supported versions

Security fixes go into the latest release. Re-run the installer or `testkit update` to get them.

## What is in scope

testkit runs on developers' machines and drives browsers, APIs and databases, so these areas matter most:

- **Installers** (`install.sh`, `install.ps1`): downloads and PATH changes.
- **CLI** (`bin/testkit*`, `bin/testkit_sync.py`): `testkit init`/`update` writes files into projects.
- **Scripts in `skills/*/scripts/`**:
  - handling of credentials and tokens;
  - read-only enforcement for databases;
  - host allow-lists;
  - redaction of evidence.
- **Instructions in skills and agents** that could make an agent touch hosts outside `qa/config.yml`, write to production, leak secrets into reports or trackers, or run billed actions without asking.

Third-party tools (browser-use, Hurl, Playwright and others) and the vendored Anthropic skills have their own security processes. Report issues in those to their maintainers. Tell us too if testkit's use of them makes the problem worse.
