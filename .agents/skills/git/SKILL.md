---
name: git
description: Ejecuta la receta determinista de publicación Git de Fuente cuando el usuario pida la cascada completa o invoque /git; las operaciones Git normales no requieren este workflow.
---

# Git - Workflow Determinista de Publicación (`/git`)

Esta habilidad automatiza de forma repetible la receta oficial de 6 pasos de publicación Git en Fuente (con soporte para repositorios estándar y Git Worktrees):

1. `git checkout <WORK_BRANCH>` (Asegura estar en la rama de trabajo `dev` o del Worktree activo)
2. `git add .`
3. `git commit -m "<mensaje>"`
4. `git push origin <WORK_BRANCH>`
5. `git checkout main && git merge <WORK_BRANCH> && git push origin main`
6. `git checkout <WORK_BRANCH>`

---

## 🚀 Instrucciones de Ejecución

Esta secuencia se usa cuando el usuario ejecuta `/git`, pide la cascada completa o autoriza explícitamente esa receta concreta:

1. **Determinar mensaje de commit**:
   - Si el usuario proporciona un mensaje junto al comando (ej. `/git "feat: actualización de componentes"`), utiliza ese mensaje.
   - Si el usuario ejecuta simplemente `/git`, omite el parámetro para que el script auto-genere el mensaje por fecha y hora: `"sesión YYYY-MM-DD HH:MM:SS"`.

2. **Ejecutar el script determinista**:
   Ejecuta el script de publicación mediante `run_command`:
   ```bash
   ./scripts/git_ship.sh "mensaje de commit opcional"
   ```

3. **Confirmación**:
   Confirma al usuario el resultado de la receta de 6 pasos.
