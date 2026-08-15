---
name: git
description: Ejecuta la receta determinista de publicación Git de Fuente cuando el usuario pida la cascada completa o invoque /git; publica la rama de trabajo, crea un PR hacia main, fusiona desde GitHub y vuelve a la rama de trabajo.
---

# Git - Workflow determinista de publicación mediante PR (`/git`)

Esta skill automatiza la publicación de Fuente sin hacer merges locales directos:

1. Asegurar la rama de trabajo activa (`dev` o el worktree activo).
2. Añadir y commitear los cambios.
3. Hacer push de la rama de trabajo.
4. Crear o reutilizar un PR de la rama de trabajo hacia `main`.
5. Fusionar el PR desde GitHub.
6. Actualizar localmente `main` por fast-forward y volver a la rama de trabajo.

## Uso

Ejecutar el script determinista:

```bash
./scripts/git_ship.sh
./scripts/git_ship.sh "feat: actualización de componentes"
```

Sin mensaje explícito se genera `sesión YYYY-MM-DD HH:MM:SS`.

El merge normal respeta las protecciones de GitHub. Si el PR queda bloqueado por
revisión o checks, el script conserva el PR abierto, vuelve a la rama de trabajo
y termina con error mostrando su URL. Solo cuando el usuario autorice
expresamente el bypass administrativo se puede usar:

```bash
./scripts/git_ship.sh --admin
./scripts/git_ship.sh "docs: publicar reglas" --admin
```

`--admin` sigue fusionando mediante el PR; únicamente permite saltarse requisitos
de protección que GitHub haya marcado como bloqueantes.

## Reglas obligatorias

- No ejecutar `git merge` directo entre ramas.
- No hacer push directo a `main`.
- Crear el PR con `gh pr create` y fusionarlo con `gh pr merge`.
- No borrar la rama `dev` después del merge.
- Si el merge no puede completarse, dejar el PR abierto y comunicar el bloqueo.
- Derivar el repositorio desde `origin`; no hardcodear propietario ni nombre.

## Confirmación

Al terminar, informar commit, rama de trabajo, URL/número del PR, commit de
merge, hashes de `dev` y `main`, estado del árbol y cualquier requisito que haya
bloqueado el PR. No afirmar que la publicación terminó si GitHub no confirma el
merge.
