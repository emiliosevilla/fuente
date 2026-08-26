# Fuente design system

Fuente is a local-first macOS knowledge studio. The interface puts the note or graph being worked on ahead of system statistics. The source plan is the authority; two local design searches were rejected because they returned a FAQ landing and a scroll-driven marketing story with forbidden remote fonts and GSAP.

## Product direction

- Audience: one person turning local files into connected, reviewed knowledge.
- Primary job: move material through `1_volcado`, `2_copiado`, `3_capturado`, `4_procesado`, and `5_compartido` without losing provenance.
- Layout: compact 68 px rail, one contextual header no taller than 64 px, one dominant workspace, quiet utility access.
- Signature: a restrained ripple connects the five-step flow and marks an active workspace transition. It never becomes background decoration.
- Type: local macOS system stacks only. Display uses the system rounded/display face where available; body and utility use the standard system sans stack.

## Semantic color tokens

| Token | Nord | Gruvbox | Purpose |
|---|---:|---:|---|
| `--surface-canvas` | `#ECEFF4` | `#282828` | App canvas |
| `--surface-raised` | `#FFFFFF` | `#32302F` | Main content |
| `--surface-sunken` | `#E5E9F0` | `#1D2021` | Recessed controls |
| `--surface-overlay` | `#FFFFFF` | `#3C3836` | Dialogs |
| `--text-primary` | `#2E3440` | `#FBF1C7` | Main text |
| `--text-secondary` | `#434C5E` | `#D5C4A1` | Supporting text |
| `--border-subtle` | `#D8DEE9` | `#504945` | Dividers |
| `--accent-primary` | `#4C6C94` | `#8EC07C` | Contrast-safe primary action |
| `--accent-selection` | Frost blue 16% | Aqua 22% | Current selection |
| `--focus-ring` | `#5E81AC` | `#83A598` | Keyboard focus |
| `--state-success` | `#4F6F41` | `#B8BB26` | Successful state |
| `--state-warning` | `#7A5E00` | `#FABD2F` | Needs attention |
| `--state-danger` | `#A83B46` | `#FF5D48` | Contrast-safe danger derived from each palette |

Nord light is the initial theme for the whole window. Gruvbox is the one global alternative. The palettes and Obsidian interaction references are adapted from Eric Davis's MIT-licensed [Obsidian Nord](https://github.com/insanum/obsidian_nord) and [Obsidian Gruvbox](https://github.com/insanum/obsidian_gruvbox) themes. Fuente keeps its own layout, typography, spacing, accessibility and component contracts.

Acceptance requires 4.5:1 for normal text and 3:1 for focus and meaningful non-text states. Values may change only after a recorded measurement and explicit approval.

## Scales

- Spacing: `4, 8, 12, 16, 24, 32, 48px`.
- Radius: `6, 10, 16px`; smaller for controls, middle for panels, largest for dialogs only.
- Controls: 32 px compact, 40 px standard, 44 px prominent.
- Icons: 16, 20, 24 px; one outline SVG/CSS language, no emoji controls.
- Content: reading measure 68ch; workspace maximum 76rem; rail 68px.
- Type: 16 px base, 17 px document, at least 14 px for controls and tables; headings use 22, 28 and 36 px.
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
- Replacement specific to Fuente and Caudal: Inicio exposes two clear product entrances, Fuente keeps reading dominant, and Caudal owns the five-step spine.
- One justified aesthetic risk: the ripple briefly carries attention between a selected step and its connected workspace, then becomes still.
- Decorations removed: stat-card grid, marketing hero copy, repeated borders, and animation without state meaning.
- How the ripple signature communicates state: one ring expands from the active flow node or rail item toward the newly active region; reduced motion shows the selected ring statically.

## Rejected alternatives

- FAQ/documentation landing: wrong product job and required remote typography.
- Scroll storytelling/parallax: wrong desktop interaction model and too motion-heavy.
- Stock card dashboard: obscures content hierarchy already measured in the baseline.
