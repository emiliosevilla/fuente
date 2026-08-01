---
name: git-ship
description: Executa la receta determinista de publicación Git de 5 pasos (add, commit, push dev, merge main, push main, checkout dev). Usar cuando el usuario pida "comitea, push, merge", "ship", "publicar" o similar.
---

# Git Ship - Workflow Determinista de Publicación

Esta habilidad automatiza de forma 100% confiable y sin desviaciones la receta de publicación Git en el proyecto Funes:

1. `git add .`
2. `git commit -m "<mensaje>"`
3. `git push origin dev`
4. `git checkout main && git merge dev && git push origin main`
5. `git checkout dev`

---

## 🚀 Instrucciones de Ejecución

Cuando el usuario pida *"comitea, push, merge"*, *"publicar"*, *"ship"* o cualquier variante similar:

1. Determina el mensaje de commit:
   - Si el usuario proporciona un mensaje o descripción en su solicitud, úsala.
   - Si no proporciona ningún mensaje, omite el argumento y el script auto-generará un mensaje con la marca de fecha y hora actual: `"sesión YYYY-MM-DD HH:MM:SS"`.

2. Ejecuta el script determinista mediante la herramienta `run_command`:
   ```bash
   ./scripts/git_ship.sh "mensaje de commit opcional"
   ```

3. Confirma al usuario el resultado de la publicación.
