# Fuente
## User job
Find and read local notes without creating a second editor or graph.
## Information hierarchy
Context header; search and reader controls; compact library; dominant read-only document; optional context drawer.
## ASCII wireframe
```text
| rail | Fuente                                      Obsidian |
|      | search and reading controls                          |
|      | library | read-only document | context drawer closed |
```
## States: loading, empty, ready, error, disabled
Library and document keep separate status regions; empty search offers reset; errors retain the query; editing remains in Obsidian.
## Keyboard order
Rail, header action, search, library controls and notes, document actions and content, context toggle, drawer controls.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
At 1024 the context drawer stays closed and the library can narrow; at 1280 the document retains at least 52% of workspace width. The reading measure stays near 68ch.
## MASTER.md overrides
Use `--library-width`; the context drawer and chat are closed by default; the full graph and all editing stay in Obsidian.
## Rejected generic alternative and reason
Three equal columns make metadata as important as the document and harm reading.
