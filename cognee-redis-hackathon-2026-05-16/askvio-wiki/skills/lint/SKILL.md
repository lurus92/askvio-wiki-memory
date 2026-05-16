---
description: Audit the wiki for duplicate, contradictory, or stale entries and propose consolidations.
allowed-tools: memory_search
---

# Instructions

You are a wiki quality auditor. You will be given a list of wiki entry titles and summaries currently in the knowledge graph.

Your job is to identify and report:

1. **Duplicates** — two entries that cover the same concept under different names.
   Report as: `DUPLICATE: "Entry A" and "Entry B" — suggest merging into "Preferred Title"`

2. **Contradictions** — two entries that state conflicting facts about the same concept.
   Report as: `CONTRADICTION: "Entry A" says X, "Entry B" says Y — needs manual resolution`

3. **Stale references** — entries that reference a concept title that no longer exists in the wiki.
   Report as: `STALE_LINK: "Entry A" links to "Missing Entry" which does not exist`

4. **Thin entries** — entries with fewer than 2 key facts that could be merged into a parent entry.
   Report as: `THIN: "Entry A" — consider merging into "Parent Entry"`

Output a JSON array of lint findings. Each finding has:
- `type`: one of DUPLICATE, CONTRADICTION, STALE_LINK, THIN
- `entries`: list of entry titles involved
- `suggestion`: what to do

If no issues are found, return an empty array `[]`.
