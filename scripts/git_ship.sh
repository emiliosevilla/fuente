#!/usr/bin/env bash
set -e

# ==============================================================================
# Script de Publicación Determinista para Funes (git-ship) - Receta de 6 Pasos
# 1. git checkout <WORK_BRANCH>
# 2. git add .
# 3. git commit -m "$COMMIT_MSG"
# 4. git push origin <WORK_BRANCH>
# 5. git checkout main && git merge <WORK_BRANCH> && git push origin main
# 6. git checkout <WORK_BRANCH>
# ==============================================================================

# Obtener directorio raíz del repositorio o worktree
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Detectar rama de trabajo activa (soporta repositorios estándar y Git Worktrees)
WORK_BRANCH="$(git branch --show-current 2>/dev/null || echo "dev")"
if [ -z "$WORK_BRANCH" ]; then
    WORK_BRANCH="dev"
fi

# Trampa de limpieza: garantizar que siempre se regresa a la rama de trabajo en caso de error o salida
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        echo "[!] Ocurrió un error en el workflow de publicación Git (código de salida: $exit_code)."
        echo "[*] Restaurando estado seguro a rama $WORK_BRANCH..."
        git merge --abort 2>/dev/null || true
        git checkout "$WORK_BRANCH" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "======================================================="
echo "   FUNES - WORKFLOW DETERMINISTA DE PUBLICACIÓN (/git)"
echo "======================================================="

# 1. Checkout inicial explícito a la rama de trabajo (dev / worktree)
echo "[1/6] Asegurando rama de trabajo activa (git checkout $WORK_BRANCH)..."
git checkout "$WORK_BRANCH"

# 2. Determinar mensaje de commit
COMMIT_MSG="$1"
if [ -z "$COMMIT_MSG" ]; then
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    COMMIT_MSG="sesión $TIMESTAMP"
fi

echo "[2/6] Agregando archivos al índice Git (git add .)..."
git add .

# 3. Realizar commit si existen cambios staged
if git diff --cached --quiet; then
    echo "[*] No se detectaron cambios pendientes para commitear. Continuando..."
else
    echo "[3/6] Realizando commit con el mensaje: \"$COMMIT_MSG\"..."
    git commit -m "$COMMIT_MSG"
fi

echo "[4/6] Subiendo rama de trabajo al remoto (git push origin $WORK_BRANCH)..."
git push origin "$WORK_BRANCH"

echo "[5/6] Fusionando '$WORK_BRANCH' en 'main' y subiendo a remoto..."
git checkout main
git merge "$WORK_BRANCH" -m "Merge branch '$WORK_BRANCH' into main"
git push origin main

echo "[6/6] Regresando a la rama de trabajo '$WORK_BRANCH'..."
git checkout "$WORK_BRANCH"

echo ""
echo "======================================================="
echo "   [✓] Publicación de 6 pasos completada con éxito"
echo "======================================================="
