# greg_personal_tools

Greg Hills' personal tools repo. It serves two purposes:

1. A **Claude Code plugin marketplace** (`greg-tools` plugin) — a small set of
   generic, public-safe skills you can install into any project with Claude Code.
2. A standalone **podcast transcript** utility (see
   [`README_podcast_transcripts.md`](./README_podcast_transcripts.md)).

---

## Claude Code Plugin: `greg-tools`

A bundle of generic, public-safe Claude Code skills. One plugin, several skills,
one-command install.

### Install

In any project, from inside Claude Code:

```text
/plugin marketplace add gwh2002/greg_personal_tools
/plugin install greg-tools@greg-personal-tools
```

- The first command registers this repo as a marketplace named
  `greg-personal-tools`.
- The second installs the `greg-tools` plugin from it.
- Update later with `/plugin marketplace update greg-personal-tools`.

### Local development / testing

To try the plugin without installing from GitHub, clone this repo and run:

```bash
claude --plugin-dir ./greg-tools
```

Validate the manifests:

```bash
claude plugin validate ./greg-tools     # plugin manifest
claude plugin validate .                 # marketplace manifest
```

### Invocation / namespacing

Skills trigger automatically from their descriptions (e.g. "make me a
business-facing diagram of this workflow"). You can also invoke them explicitly
with the plugin namespace:

```text
/greg-tools:biz-diagram
/greg-tools:excalidraw-diagram
/greg-tools:sheet-download
/greg-tools:sync-docs
/greg-tools:pending
```

### Skill showcase

| Skill | What it does | Notes / prerequisites |
|---|---|---|
| **biz-diagram** | Stakeholder-facing, three-lane Excalidraw process diagram, rendered to PNG via a bundled Pillow renderer (`bin/render_biz_diagram_png.py`). For business audiences — no scripts/paths/schemas. | `pip install "Pillow>=10"` |
| **excalidraw-diagram** | Technical Excalidraw diagrams that *argue visually* — evidence artifacts, multi-zoom layout, and a Playwright render-and-fix validation loop. Brand-customizable via `references/color-palette.md`. | `uv` + `playwright install chromium` for the render loop |
| **sheet-download** | Downloads a Google Sheet to a local CSV at a path you specify. | A connected Google account (e.g. a Google Drive/Sheets MCP server) |
| **sync-docs** | Syncs Google Docs to local markdown via a small YAML registry, with a frontmatter contract and optional push-back. | A connected Google Docs/Drive account (e.g. via MCP) |
| **pending** | Scans the current conversation and working tree for loose ends: uncommitted changes, open issues/PRs, unfinished action items, missing changelog updates. | None |

The `excalidraw-diagram` skill is vendored from the open-source
[excalidraw-diagram-skill](https://github.com/coleam00/excalidraw-diagram-skill).

### Why one plugin (not one-per-skill)?

A single `greg-tools` plugin means a single `/plugin install`. With only a
handful of skills, per-skill plugins would add install friction for no real
benefit. If the skill count grows or skills diverge in their dependencies, the
bundle can be split later — the marketplace already supports multiple plugin
entries.

### Repo layout

```text
greg_personal_tools/
├── .claude-plugin/
│   └── marketplace.json          # marketplace catalog (name: greg-personal-tools)
├── greg-tools/                    # the plugin
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── bin/
│   │   └── render_biz_diagram_png.py
│   └── skills/
│       ├── biz-diagram/SKILL.md
│       ├── excalidraw-diagram/SKILL.md   (+ references/)
│       ├── sheet-download/SKILL.md
│       ├── sync-docs/SKILL.md
│       └── pending/SKILL.md
├── README.md
├── README_podcast_transcripts.md
└── podcast_transcripts.py ...
```
