# Caudal
## User job
See where material is in the five-stage pipeline and open the existing operational controls.
## Information hierarchy
Context header; five-stage spine; one primary action; current operations; detail drawer closed by default.
## ASCII wireframe
```text
| rail | Caudal                              process material |
|      | 1 Volcado  2 Copiado  3 Capturado                 |
|      | 4 Procesado  5 Compartido                          |
|      | operations summary | detail drawer closed          |
```
## States: loading, empty, ready, error, disabled
All five cells remain visible and named; counts may be unmeasured; errors name recovery; unavailable actions explain their prerequisite.
## Keyboard order
Rail, primary action, detail trigger, existing operation controls, compact counters, drawer controls when open.
## Window behavior: 1024×700, 1280×850, 1440×900, maximized
The five cells share the available width at every acceptance size. Text truncates inside a cell before the page gains horizontal scroll.
## MASTER.md overrides
The pipeline is never a carousel. Tables, approvals, quarantine and logs retain their existing owners and open below or on demand.
## Rejected generic alternative and reason
Five independent cards hide sequence and encourage duplicated actions.
