---
name: biz-diagram
description: Create business-facing Excalidraw diagrams for stakeholders. Use when the user asks for a biz diagram, business-facing diagram, stakeholder Excalidraw, executive process diagram, or a visual that should explain a workflow without technical implementation detail.
---

# Business-Facing Excalidraw Diagram

Use this skill when the audience is business users: leadership, analysts,
customers, or other stakeholders who need to understand how a process works
without reading scripts, repo paths, schemas, or housekeeping detail.

This skill produces a clean three-lane process diagram and renders it to PNG
with a bundled Pillow renderer (`bin/render_biz_diagram_png.py`). No Excalidraw
CLI is required.

## When To Use

- Use for conceptual business overviews: "how does this process work?", "what
  happens before review?", or "what does the stakeholder need to know?"
- Use when the user says "create a biz diagram", "business-facing diagram",
  "Excalidraw for stakeholders", "executive process diagram", or
  "stakeholder overview".
- Do not use for technical pipeline documentation. Detailed script-level,
  schema-level, file-path, or troubleshooting diagrams belong in the
  `excalidraw-diagram` skill instead.

## Layout Constants

- Canvas: 1600x900.
- Maximum lanes: 3.
- Lane top: `y=128`.
- Lane height: about 546.
- Lane widths: about 440 each with 18px gaps; the final lane may be about 500.
- Each lane uses a colored border plus a very light tinted background.
- Place the `.excalidraw` and exported `.png` at a topic root level the user
  names; do not assume a private directory layout.

## Palette

| Step | Use | Border | Lane fill | Content box fill |
| --- | --- | --- | --- | --- |
| Step 1 | Identify / source | `#c2410c` | `#fff7ed` | `#fed7aa` |
| Step 2 | Process / extract | `#6d28d9` | `#f5f3ff` | `#ddd6fe` |
| Step 3 | Review / output | `#047857` | `#f0fdf4` | `#bbf7d0` |

## Text Rules

- Title and subtitle at the top, written for business readers.
- Lane header: small all-caps badge in the lane color, formatted
  `STEP N -- LABEL`, followed by a large bold plain-English title.
- Content: short `-` bullet points with plain verbs.
- Avoid filenames, `.py`, `.csv`, script names, repo paths, implementation
  chores, and internal cleanup steps.
- Arrows between lanes should label the gate condition, such as `complete` or
  `ready for review`.
- Use ASCII-safe characters in text that will be rendered to PNG: `-->`, `[+]`,
  `[-]`, and `--` rather than arrows, checkmarks, crosses, or em dashes.

## Required Elements

1. Title and subtitle.
2. Three step lanes with badge, large title, and content boxes.
3. Diamond gate in Step 1, such as `Inputs complete?`, with a `No --> ...`
   fallback label.
4. Horizontal arrows between lanes.
5. Red dashed correction loop from Step 3 back to Step 2.
6. Blue dashed boundary/scope footer: `What X contains: [+] ... [-] ...`.

## PNG Export

Use the bundled Pillow renderer, not an Excalidraw CLI. Build a JSON spec
(see the spec shape below), then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/render_biz_diagram_png.py" \
  path/to/biz_diagram_spec.json \
  path/to/diagram.png
```

`${CLAUDE_PLUGIN_ROOT}` is set by Claude Code to the installed plugin
directory. If it is unset, substitute the absolute path to this plugin's `bin/`
folder. The renderer requires `Pillow>=10` (`pip install Pillow`).

### Spec shape

The renderer expects a JSON object with these keys:

```json
{
  "title": "Business process overview",
  "subtitle": "How the workflow runs end to end",
  "steps": [
    {"label": "Source", "title": "Identify", "bullets": ["..."],
     "gate": {"text": "Inputs complete?", "fallback": "No --> request more"}},
    {"label": "Process", "title": "Extract", "bullets": ["..."]},
    {"label": "Review", "title": "Approve", "bullets": ["..."]}
  ],
  "arrow_labels": ["complete", "ready for review"],
  "correction_loop": "Corrections go back to Step 2",
  "scope": {"title": "What this contains", "included": ["..."], "excluded": ["..."]}
}
```

The renderer builds each lane badge automatically as `STEP N -- LABEL` from
`steps[].label`. Each step requires `label`, `title`, and a non-empty `bullets`
array; `gate` (with `text` and `fallback`) is optional and renders a decision
diamond in that lane.

PNG export rules:

- 144 DPI.
- 1600x900.
- Save the PNG alongside the `.excalidraw` file.
- Keep all renderable text ASCII-safe (the renderer asserts ASCII).
