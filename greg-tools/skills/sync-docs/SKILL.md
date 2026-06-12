---
name: sync-docs
description: Use when the user wants to sync Google Docs to local markdown, track which docs map to which local files, or pull the latest content from linked Google Docs.
---

# Sync Google Docs to Local Markdown

## Overview

Pulls (and optionally pushes) content between Google Docs and local markdown
files, tracked by a small YAML registry that maps each doc to a local path. The
agent reads/writes Doc content through a Google Docs/Drive MCP server (or any
equivalent fetch tool it has); this skill defines the registry format, the
frontmatter contract, and the sync workflow.

## Registry

Keep a registry file in the project (suggested: `docs_registry.yaml`):

```yaml
docs:
  - url: https://docs.google.com/document/d/DOC_ID/edit
    local_path: docs/some-doc.md
    title: Human-readable label
    multi_tab: true           # optional, default false
    sync_direction: pull      # optional: pull (default), push, bidirectional
```

## Commands

### Sync all docs

When the user asks to "sync docs" with no argument:

1. For each registry entry, fetch the latest Doc content (Docs/Drive MCP tool).
2. Write it to the entry's `local_path` with the frontmatter below.
3. Report which docs synced and any failures.

### Add a doc

When the user provides a Google Doc URL (with or without a target path):

1. Extract the document ID from the URL.
2. Fetch the doc to read its title (and tab list if multi-tab).
3. If no `local_path` was given, suggest one from the title and current context.
4. Add the entry to the registry.
5. Sync it.

### Push a registered doc

When the user asks to push a registered doc, fetch the local file, strip its
YAML frontmatter, and write the body back to the Doc via the Docs MCP tool
(requires Editor access on the target doc). Only push entries whose
`sync_direction` is `push` or `bidirectional`.

## Frontmatter Contract

Each synced markdown file gets this YAML frontmatter header:

```markdown
---
gdoc_url: https://docs.google.com/document/d/DOC_ID/edit
gdoc_id: DOC_ID
gdoc_title: Document Title
last_synced: '2026-02-09T14:30:00Z'
sync_source: google_docs
multi_tab: true
---

[Document content as markdown]
```

- On re-sync, the standard fields are refreshed; preserve any manually-added
  frontmatter fields.
- Multi-tab docs use `<!-- TAB: TabName -->` delimiters between tab content.

## Extracting the Doc ID

Handle these URL patterns:

- `https://docs.google.com/document/d/DOC_ID/edit` -> `DOC_ID`
- `https://docs.google.com/document/d/DOC_ID/edit#heading=h.xxx` -> `DOC_ID`
- `https://docs.google.com/document/d/DOC_ID` -> `DOC_ID`
- Bare ID (no slashes) -> use directly

## Common Issues

- **Auth**: requires a connected Google account (via an MCP server or
  equivalent). For push, the account needs Editor access on the doc.
- **Formatting loss**: Google Docs -> markdown is lossy (tables, images,
  comments). Content is best-effort markdown.
- **Conflicting local edits**: a pull overwrites local content below the
  frontmatter. Commit local edits first if they matter.
- **Frontmatter on push**: strip the YAML frontmatter before sending content
  back to the doc.
