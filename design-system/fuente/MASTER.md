# Fuente design system

Fuente is a local-first macOS knowledge studio. The interface puts the note, meeting, or graph being worked on ahead of system statistics. The source plan is the authority; two local design searches were rejected because they returned a FAQ landing and a scroll-driven marketing story with forbidden remote fonts and GSAP.

## Product direction

- Audience: one person turning local files and meetings into connected, reviewed knowledge.
- Primary job: move material through `1_volcado`, `2_copiado`, `3_capturado`, `4_procesado`, and `5_compartido` without losing provenance.
- Layout: compact 68 px rail, one contextual header, one dominant workspace, quiet utility access.
- Signature: a restrained ripple connects the five-step flow and marks an active workspace transition. It never becomes background decoration.
- Type: local macOS system stacks only. Display uses the system rounded/display face where available; body and utility use the standard system sans stack.

## Semantic color tokens

| Token | Energy | Zen | Purpose |
|---|---:|---:|---|
| `--surface-canvas` | `#F2F6F4` | `#071311` | App canvas |
| `--surface-raised` | `#FFFFFF` | `#0D211E` | Main content |
| `--surface-sunken` | `#E6EEEB` | `#081A17` | Recessed controls |
| `--surface-overlay` | `#FFFFFF` | `#122B27` | Dialogs |
| `--text-primary` | `#102421` | `#F1F7F4` | Main text |
| `--text-secondary` | `#506762` | `#AFC3BE` | Supporting text |
| `--border-subtle` | `#CBD8D4` | `#31504A` | Dividers |
| `--accent-primary` | `#147D73` | `#5AD8C8` | Primary action |
| `--accent-selection` | `#C9EEE8` | `#183F3A` | Current selection |
| `--focus-ring` | `#0B6F66` | `#7CE5D8` | Keyboard focus |
| `--state-success` | `#267A4B` | `#76D69B` | Successful state |
| `--state-warning` | `#8A5A00` | `#F2C66D` | Needs attention |
| `--state-danger` | `#B53B3B` | `#FF8D89` | Failure or danger |

Acceptance requires 4.5:1 for normal text and 3:1 for focus and meaningful non-text states. Values may change only after a recorded measurement and explicit approval.

## Scales

- Spacing: `4, 8, 12, 16, 24, 32, 48px`.
- Radius: `6, 10, 16px`; smaller for controls, middle for panels, largest for dialogs only.
- Controls: 32 px compact, 40 px standard, 44 px prominent.
- Icons: 16, 20, 24 px; one outline SVG/CSS language, no emoji controls.
- Content: reading measure 68ch; workspace maximum 76rem; rail 68px.
- Motion: 120ms fast and 200ms standard, transform/opacity only, final state immediate under reduced motion.
- Elevation: canvas, raised panel, overlay. Shadows are reserved for overlays.

## Desktop interaction rules

- Visual and keyboard order must match. Route changes focus the destination heading.
- Every dialog has one title, one named close control, Escape, trapped focus, backdrop policy, and opener restoration.
- Loading/empty/ready use `role="status"`; errors use `role="alert"`; unavailable actions use native `disabled` plus visible explanation.
- Test 1024×700, 1280×850, 1440×900, and maximized without page-level horizontal scrolling.
- Applicable guidance: contrast, keyboard, semantic controls, focus visibility, readable measure, desktop rail, state clarity, reduced motion.
- Excluded mobile-only guidance: safe areas, phone breakpoints, bottom navigation, system gestures, and touch-only target assumptions.

## Distinctiveness review

- Generic choice found: the old uniform statistics row and equal-weight toolbar read as an admin dashboard.
- Replacement specific to Fuente: the five-step material flow becomes Inicio's spine; current notes, meetings, and connections become primary workspaces.
- One justified aesthetic risk: the ripple briefly carries attention between a selected step and its connected workspace, then becomes still.
- Decorations removed: stat-card grid, marketing hero copy, repeated borders, and animation without state meaning.
- How the ripple signature communicates state: one ring expands from the active flow node or rail item toward the newly active region; reduced motion shows the selected ring statically.

## Rejected alternatives

- FAQ/documentation landing: wrong product job and required remote typography.
- Scroll storytelling/parallax: wrong desktop interaction model and too motion-heavy.
- Stock card dashboard: obscures content hierarchy already measured in the baseline.
