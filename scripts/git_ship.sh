#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Publicación determinista de Fuente mediante Pull Request.
# 1. checkout de la rama de trabajo
# 2. add + commit
# 3. push de la rama de trabajo
# 4. crear o reutilizar PR hacia main
# 5. merge del PR en GitHub
# 6. fast-forward local de main y regreso a la rama de trabajo
# ============================================================================

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

WORK_BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$WORK_BRANCH" ]]; then
    echo "[!] No se pudo determinar la rama de trabajo activa." >&2
    exit 1
fi

BASE_BRANCH="${BASE_BRANCH:-main}"
if [[ "$WORK_BRANCH" == "$BASE_BRANCH" ]]; then
    echo "[!] La rama de trabajo ($WORK_BRANCH) coincide con la rama base ($BASE_BRANCH)." >&2
    echo "[!] Ejecuta /git desde una rama de trabajo, normalmente dev." >&2
    exit 1
fi

COMMIT_MSG=""
ADMIN_MERGE=false

for arg in "$@"; do
    if [[ "$arg" == "--admin" ]]; then
        ADMIN_MERGE=true
    elif [[ -z "$COMMIT_MSG" ]]; then
        COMMIT_MSG="$arg"
    else
        echo "[!] Uso: $0 [mensaje de commit] [--admin]" >&2
        exit 2
    fi
done

if ! command -v gh >/dev/null 2>&1; then
    echo "[!] gh no está instalado; no se puede crear ni fusionar el PR." >&2
    exit 1
fi

if ! gh auth status --hostname github.com >/dev/null 2>&1; then
    echo "[!] gh no está autenticado contra github.com." >&2
    exit 1
fi

PR_URL=""

cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo ""
        echo "[!] El workflow de publicación terminó con error (código $exit_code)."
        git checkout "$WORK_BRANCH" 2>/dev/null || true
        if [[ -n "$PR_URL" ]]; then
            echo "[*] PR pendiente: $PR_URL"
        fi
    fi
}
trap cleanup EXIT

echo "======================================================="
echo "   FUENTE - WORKFLOW DE PUBLICACIÓN MEDIANTE PR"
echo "======================================================="

echo "[1/6] Asegurando rama de trabajo activa: $WORK_BRANCH"
git checkout "$WORK_BRANCH"

if [[ -z "$COMMIT_MSG" ]]; then
    COMMIT_MSG="sesión $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo "[2/6] Agregando cambios y creando commit"
git add .
if git diff --cached --quiet; then
    echo "[*] No hay cambios pendientes para commitear. Continuando con la publicación del PR."
else
    git commit -m "$COMMIT_MSG"
fi

echo "[3/6] Publicando $WORK_BRANCH"
git push -u origin "$WORK_BRANCH"

ORIGIN_URL="$(git remote get-url origin)"
REPOSITORY="$(printf '%s' "$ORIGIN_URL" | sed -E 's#^https://github.com/##; s#^git@github.com:##; s#\.git$##')"
if [[ ! "$REPOSITORY" =~ ^[^/]+/[^/]+$ ]]; then
    echo "[!] El remoto origin no es un repositorio GitHub reconocible: $ORIGIN_URL" >&2
    exit 1
fi

echo "[4/6] Creando o reutilizando PR $WORK_BRANCH → $BASE_BRANCH"
PR_URL="$(gh pr list \
    --repo "$REPOSITORY" \
    --state open \
    --head "$WORK_BRANCH" \
    --base "$BASE_BRANCH" \
    --json url \
    --jq '.[0].url')"

if [[ -z "$PR_URL" ]]; then
    PR_TITLE="${COMMIT_MSG%%$'\n'*}"
    PR_BODY=$'Publicación automática de Fuente mediante Pull Request.\n\nEl merge entre ramas se realiza desde GitHub; no se ejecuta un merge local directo.'
    PR_URL="$(gh pr create \
        --repo "$REPOSITORY" \
        --base "$BASE_BRANCH" \
        --head "$WORK_BRANCH" \
        --title "$PR_TITLE" \
        --body "$PR_BODY" \
        --no-maintainer-edit)"
fi
echo "[*] PR: $PR_URL"

PR_NUMBER="$(gh pr view "$PR_URL" --repo "$REPOSITORY" --json number --jq '.number')"

echo "[5/6] Fusionando el PR desde GitHub"
if [[ "$ADMIN_MERGE" == true ]]; then
    gh pr merge "$PR_NUMBER" --repo "$REPOSITORY" --admin --merge --delete-branch=false
else
    gh pr merge "$PR_NUMBER" --repo "$REPOSITORY" --merge --delete-branch=false
fi

PR_STATE="$(gh pr view "$PR_NUMBER" --repo "$REPOSITORY" --json state --jq '.state')"
if [[ "$PR_STATE" != "MERGED" ]]; then
    echo "[!] GitHub no confirmó el merge del PR $PR_NUMBER (estado: $PR_STATE)." >&2
    exit 1
fi

echo "[6/6] Actualizando main por fast-forward y regresando a $WORK_BRANCH"
git fetch origin "$BASE_BRANCH"
git checkout "$BASE_BRANCH"
git pull --ff-only origin "$BASE_BRANCH"
git checkout "$WORK_BRANCH"

echo ""
echo "======================================================="
echo "   [✓] Publicación mediante PR completada"
echo "   PR: $PR_URL"
echo "======================================================="
