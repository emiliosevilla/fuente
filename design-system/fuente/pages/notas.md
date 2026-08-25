# Notas
## User job
Find, read, edit, understand, and prepare a note without leaving the reading context.
## Information hierarchy
Search; compact library; dominant document; optional context with assistant, preparation, and discussion.
## ASCII wireframe
```text
| rail | Notas                  search  theme  guide settings |
|      | [full phrase search]                               |
|      | library |          document          | context     |
|      |         | reading / editor           | tabs        |
```
## States: loading, empty, ready, error, disabled
Library and document own separate status regions; empty search offers reset; errors retain the query; sharing stays disabled with a reason until review.
## Keyboard order
Rail, search, library controls and notes, document actions/content, context toggle, tabs, active panel controls.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
At 1024 context collapses and library narrows; at 1280 the document retains at least 55% of workspace width; reading measure stays near 68ch.
## MASTER.md overrides
Use a `--library-width` token; Map opens its independent workspace and never consumes document width.
## Rejected generic alternative and reason
Three equal columns make metadata as important as the document and harm reading.
