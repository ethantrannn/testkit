# Third-party notices

testkit is MIT-licensed (see [LICENSE](LICENSE)). It bundles or generates the components below, which keep their own licenses.

## Bundled in this repository

| Component | Path | Source | License |
|---|---|---|---|
| docx skill | `skills/docx/` | [anthropics/skills](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/docx) @ `e4bb5d9` | Apache-2.0, © Anthropic (`skills/docx/LICENSE.txt`) |
| pdf skill | `skills/pdf/` | [anthropics/skills](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/pdf) @ `e4bb5d9` | Apache-2.0, © Anthropic (`skills/pdf/LICENSE.txt`) |
| xlsx skill | `skills/xlsx/` | [anthropics/skills](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/xlsx) @ `e4bb5d9` | Apache-2.0, © Anthropic (`skills/xlsx/LICENSE.txt`) |
| pptx skill | `skills/pptx/` | [anthropics/skills](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/pptx) @ `e4bb5d9` | Apache-2.0, © Anthropic (`skills/pptx/LICENSE.txt`) |

These folders are copied unmodified. Each has a `SOURCE.txt` with the exact upstream commit. Do not edit them in place; replace the whole folder with a newer upstream copy.

## Generated on the user's machine (not redistributed)

| Component | Where it appears | Source | License |
|---|---|---|---|
| browser-use skill | `<skills dir>/browser-use/` in a project, written by `browser-use skill install` during `testkit init` | [browser-use/browser-use](https://github.com/browser-use/browser-use) | MIT |
| agent-browser references | `<skills dir>/browser-testing/references/`, written by `agent-browser skills get` (only if agent-browser is installed) | [agent-browser](https://www.npmjs.com/package/agent-browser) | see the package |

## Tools used at runtime (installed separately, not bundled)

Graphiti MCP server (`zepai/knowledge-graph-mcp` Docker image with FalkorDB, Apache-2.0, started on demand by `testkit graph up`), uv, browser-use CLI, Google Chrome, pandoc, Hurl, Mailpit, k6, Maestro, Playwright, Lighthouse, axe-core (loaded from a CDN into the page under test), OWASP ZAP, LibreOffice, poppler, ffmpeg, and the Python packages pinned in each script's inline metadata (python-docx, openpyxl, pdfplumber, Faker, Pillow, python-pptx, PyYAML, mcp). Each is used under its own license. The installers download them from their official sources.
