# Mapa
## User job
Explore note relations and provenance, then return to the note without losing context.
## Information hierarchy
Graph canvas; zoom/center controls; stable counters and legend; selected-node detail.
## ASCII wireframe
```text
| rail | Mapa                   search  theme  guide settings |
|      | [-] [+] [Centrar] counters                         |
|      |                 graph canvas                       |
|      | legend / selected relation                         |
```
## States: loading, empty, ready, error, disabled
Loading preserves the canvas bounds; empty explains how links appear; ready exposes controls; error offers reload; unavailable provenance is explained.
## Keyboard order
Rail, zoom out, zoom in, center, graph nodes, selected relation, return to Notes.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
Controls wrap above the canvas at 1024; labels remain stable and the canvas fills remaining height at every size.
## MASTER.md overrides
The graph remains one engine and one state source; no duplicate embedded graph in Notes.
## Rejected generic alternative and reason
Embedding a small graph beside the reader weakens both reading and relationship exploration.
