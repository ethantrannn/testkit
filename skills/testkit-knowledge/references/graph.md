# The Graphiti graph

[Graphiti](https://github.com/getzep/graphiti) (Apache-2.0) turns text episodes into a temporal knowledge graph: entities, facts with `valid_at` / `invalid_at`, and the episodes they came from. testkit uses its MCP server over HTTP (`…/mcp`) and keeps one `group_id` per project (`knowledge.group_id`, default: the project folder name as a slug).

## Finding a graph

`kg.py detect` (and `testkit graph detect`) try, in order: `knowledge.graphiti.url` in `qa/config.yml`; env `TESTKIT_GRAPHITI_URL`; MCP entries whose name contains `graphiti` with an http URL in `.mcp.json`, `~/.claude.json`, `~/.codex/config.toml`, `.codex/config.toml`, `.cursor/mcp.json`, `~/.cursor/mcp.json`, `~/.gemini/settings.json`, `.gemini/settings.json`, `.vscode/mcp.json`; then `http://localhost:8000`. A candidate counts only if `/health` answers like Graphiti (`"service":"graphiti-mcp"`), so another service on the same port is ignored. The endpoint is `/mcp` (Graphiti 1.1.x redirects `/mcp/` to `/mcp`).

## Local stack (`testkit graph …`, terminal)

- `testkit graph up` reuses a reachable graph, else writes `~/.testkit/graphiti/` (`TESTKIT_HOME`) and starts `zepai/knowledge-graph-mcp:1.1.3-graphiti-0.31.2` (FalkorDB + MCP server in one container; ~3.7 GB download, ~11 GB on disk) bound to `127.0.0.1:8000`, telemetry off, restart unless-stopped. API keys are copied from your shell environment into `.env` (mode 600); they are never printed.
- Provider: `--provider openai|anthropic|gemini|groq|azure_openai|ollama`, `--model`, `--embedder openai|gemini|voyage|azure_openai|ollama`. Default: the first key found (`OPENAI_API_KEY` → OpenAI for both; `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY`/`OPENAI_API_KEY`/`GOOGLE_API_KEY` for embeddings; `GOOGLE_API_KEY` → Gemini). Anthropic, Groq and Ollama need `--model`. Anthropic/Groq without an OpenAI or Gemini key use a local reranker that downloads ~2.3 GB on first search.
- `status`, `logs --tail N`, `down` (keeps data), `uninstall [--purge]` (purge deletes the graph data), `connect --agents claude,codex,gemini` (registers the URL in the agents' user config; prints steps for Cursor/Copilot). `--expose-db` also binds FalkorDB (6379) and its browser UI (3000) to 127.0.0.1.

## What works without an API key

| Works | Fails |
|---|---|
| server start, `/health`, `get_status`, `get_episodes`, `delete_episode`, `clear_graph` | `add_memory` is accepted ("queued") but processing fails in the background: the episode is never stored. `kg.py status` reports it as `failed` after 15 minutes. |
| `kg.py` files-only mode: decisions, map, registry, file search, pending queue | `search_nodes`, `search_memory_facts` (need the embedder) |
| | `add_triplet` (`kg.py fact`) needs the embedder, and the LLM as soon as a similar entity already exists |

The MCP server 1.1.3 has no `sentence_transformers` embedder. Fully local option: Ollama with a capable chat model plus `nomic-embed-text` (`testkit graph up --provider ollama --model <model>`); small models often produce invalid JSON and fail extraction.

## Cost and privacy

Each episode costs several LLM calls (entity extraction, deduplication, summaries) plus embeddings. Large documents are split into sections of `knowledge.ingest.max_chunk_chars`. Everything sent goes to the configured provider; hence the consent step. `kg.py` redacts secrets and masks e-mails and phone numbers before sending, and never logs keys.

## Episodes and keys

Every episode has a stable key: `D-…` (decision), `map#<section>`, `doc:<id>#<section>`, `run:<RUN_ID>`, `bug:<BUG_ID>#<status>`. The name stored in the graph is `<key>: <title>`. `.graph-state.json` (git-ignored, per machine) records what this machine sent to which graph: unchanged content is skipped, changed content replaces the old episode (`delete_episode` + `add_memory`). Graphiti processes episodes asynchronously, so new knowledge appears in search after the LLM finishes (seconds to minutes).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `graph unreachable` | `testkit graph status`; start Docker; `testkit graph up`. Work continues from files; `kg.py flush` sends the queue later. |
| episodes `failed` | `testkit graph logs --tail 200` (look for `401`, `429`, `model not found`, JSON validation errors); fix key/model, `testkit graph up --force` to rewrite the config, then `kg.py flush --retry-failed`. |
| `429` rate limits | `testkit graph up --force --concurrency 1` |
| search error `Connection error` | the embedder/LLM endpoint is unreachable or not configured |
| wrong project data | check `knowledge.group_id`; agents calling MCP tools directly must pass it |
