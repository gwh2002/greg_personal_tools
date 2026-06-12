---
name: sheet-download
description: Use when the user provides a Google Sheets URL and wants to download it to a local folder path as CSV.
---

# Sheet Download

## Overview

Downloads a Google Sheet to a local CSV file with sensible naming. Requires a
Google Drive / Sheets MCP server (or any equivalent tool the agent has for
reading Sheets content).

## Usage Pattern

When the user provides: `<Google Sheets URL> <target folder path>`

## Steps

1. **Extract spreadsheet ID** from the URL.
   - Pattern: `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
   - Extract the ID between `/d/` and `/edit`.

2. **Get sheet metadata** (e.g. via a Drive search tool) to retrieve the
   actual sheet name.

3. **Get sheet content** (e.g. via a Sheets "get content" tool).
   - Use a broad range like `A1:ZZ10000` to capture all data.
   - If multiple sheets/tabs exist, ask the user which one or download all.

4. **Format as CSV.**
   - First row as header.
   - Comma-separated values; empty cells as consecutive commas.
   - Apply standard CSV escaping for values containing commas or quotes.

5. **Determine the filename.**
   - Base it on the sheet name from metadata.
   - Sanitize: lowercase, replace spaces with underscores, extension `.csv`.
   - For a dated snapshot: `YYYY.MM.DD_[sheet_name].csv`.

6. **Write the file** with the `Write` tool to
   `{target_folder_path}/{filename}` (use the path the user supplied; resolve it
   relative to the current working directory if it is not absolute). Write pure
   CSV data with no metadata header.

## Example

User: "Download this sheet to ./data/:
https://docs.google.com/spreadsheets/d/1ABC123XYZ/edit"

```text
1. Extract ID: 1ABC123XYZ
2. Get metadata -> name: "Q4 Planning"
3. Get content for range A1:ZZ10000
4. Format as CSV
5. Filename: q4_planning.csv (or 2026.01.12_q4_planning.csv if dated)
6. Write to ./data/q4_planning.csv
```

## Common Issues

- **Multiple sheets/tabs**: ask which one, or download all with the tab name in
  each filename.
- **Large sheets**: may need to paginate or limit the range.
- **Empty cells**: preserve structure with consecutive commas.
- **Special characters in names**: sanitize for filesystem compatibility.
- **Commas/quotes in cell values**: use proper CSV escaping.
- **Auth**: the agent needs a connected Google account (via an MCP server or
  equivalent) with read access to the sheet.
