#!/usr/bin/env bash
set -e

# ==============================================================================
# Script de Publicación Determinista para Funes (git-ship)
# Ejecuta la receta de 5 pasos:
# 1. git add .
# 2. git commit -m "$COMMIT_MSG"
# 3. git push origin dev
# 4. git checkout main && git merge dev && git push origin main
# 5. git checkout dev
# ==============================================================================

# Obtener directorio raíz del repositorio
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

INITIAL_BRANCH="$(git branch --show-current 2>/dev/null || echo "dev")"

# Trampa de limpieza: garantizar que siempre se regresa a la rama dev en caso de error o salida
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo ""
        echo "[!] Ocurrió un error en el workflow de publicación Git (código de salida: $exit_code)."
        echo "[*] Restaurando estado seguro a rama dev..."
        git merge --abort 2>/dev/null || true
        git checkout dev 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "======================================================="
echo "        FUNES - WORKFLOW DETERMINISTA DE PUBLICACIÓN"
echo "======================================================="

# 1. Asegurar que estamos en la rama dev
if [ "$INITIAL_BRANCH" != "dev" ]; then
    echo "[*] Cambiando a rama 'dev'..."
    git checkout dev
fi

# 2. Determinar mensaje de commit
COMMIT_MSG="$1"
if [ -z "$COMMIT_MSG" ]; then
    TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
    COMMIT_MSG="sesión $TIMESTAMP"
fi

echo "[1/5] Agregando archivos al índice Git (git add .)..."
git add .

# Verificar si hay cambios staged para commitear
if git diff --cached --quiet; then
    echo "[*] No se detectaron cambios pendientes para commitear. Continuando..."
else
    echo "[2/5] Realizando commit con el mensaje: \"$COMMIT_MSG\"..."
    git commit -m "$COMMIT_MSG"
fi

echo "[3/5] Subiendo rama 'dev' al remoto (git push origin dev)..."
git push origin dev

echo "[4/5] Fusionando 'dev' en 'main' y subiendo a remoto..."
git checkout main
git merge dev -m "Merge branch 'dev' into main"
git push origin main

echo "[5/5] Regresando a la rama de trabajo 'dev'..."
git checkout dev

echo ""
echo "======================================================="
echo "   [✓] Publicación completada con éxito en dev y main"
echo "======================================================="
