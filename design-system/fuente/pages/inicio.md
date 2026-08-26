# Inicio
## User job
See whether the local system is ready and enter Fuente or Caudal.
## Information hierarchy
Context header; local status; Fuente and Caudal access; setup and diagnostics; recent activity.
## ASCII wireframe
```text
| rail | Inicio                                      guide   |
|      | Local status: Vault, local AI, connection           |
|      | Fuente access          | Caudal access              |
|      | Setup and diagnostics | Recent activity            |
```
## States: loading, empty, ready, error, disabled
Loading keeps both product entrances visible; empty explains how to configure the Vault; ready exposes both actions; error names recovery; disabled explains the missing prerequisite.
## Keyboard order
Inicio, Fuente, Caudal, global theme, Ajustes, guide, Fuente access, Caudal access, setup and diagnostics, activity.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
At 1024 the two access blocks remain legible and can scroll inside their carousel; wider sizes show both. No page-level horizontal scroll.
## MASTER.md overrides
The ripple may animate only the active workspace transition.
## Rejected generic alternative and reason
A statistics dashboard gives equal weight to diagnostics and hides the two product entrances.
