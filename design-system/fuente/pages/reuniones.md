# Reuniones
## User job
See local Meetily recordings, understand their state, and import the chosen meeting into Fuente.
## Information hierarchy
Meeting library; selected recording state; direct open, refresh, and import actions.
## ASCII wireframe
```text
| rail | Reuniones              search  theme  guide settings |
|      | recent recordings | selected state and next action |
|      | recording history | import result                  |
```
## States: loading, empty, ready, error, disabled
Loading names the local scan; empty points to Abrir Meetily; ready lists recordings; error offers retry; import is disabled with a visible reason when unavailable.
## Keyboard order
Rail, open Meetily, refresh, recording list, selected recording, import.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
The library becomes one column at 1024 and a library/detail split above 1280; actions remain visible without horizontal scroll.
## MASTER.md overrides
Library comes before explanation; no marketing hero or decorative process timeline.
## Rejected generic alternative and reason
A promotional hero repeats product claims while hiding the recordings people came to use.
