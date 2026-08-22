---
name: git
description: Ejecuta la publicación completa de Fuente cuando el usuario escriba exactamente git, invoque $git o pida expresamente la cascada completa. Publica dev y promociona hacia main mediante Pull Request con merge commit. No usar para consultas Git ni para commits, pushes o PRs aislados.
---

# Git: publicación segura de Fuente

Usar la receta determinista del repositorio. No reconstruir la cascada con
comandos Git manuales.

## Ramas y reglas inmutables

1. Tratar `main` como rama protegida. `dev` es la rama de trabajo normal.
2. La única promoción válida es `dev -> main`, siempre mediante Pull Request.
3. No ejecutar `git merge`, squash, rebase ni fast-forward local para
   promocionar `dev` a `main`. Sí está permitido y es obligatorio actualizar
   cada copia local desde su propio `origin/<rama>` por fast-forward después de
   que GitHub confirme el merge.
4. Crear el PR con `gh pr create` y fusionarlo con `gh pr merge --merge`.
5. Verificar que GitHub confirme el merge y que el commit resultante de `main`
   tenga dos padres. No afirmar publicación completada antes de esa verificación.
6. Detenerse en el primer fallo, salvo el bloqueo del merge normal cubierto por
   la regla siguiente. Si el PR queda bloqueado por revisiones, checks o
   políticas ajenas a ese caso, dejarlo abierto y comunicar la URL y el motivo.
7. Al invocar `$git`, escribir `git` exactamente o solicitar inequívocamente
   la cascada completa, el usuario autoriza de forma explícita: `git add .`,
   crear el commit de los cambios comprobados en el preflight, hacer push de
   `dev`, crear o reutilizar el PR `dev -> main` y fusionarlo con
   `gh pr merge --admin --merge` cuando sea necesario. Esta autorización debe
   reflejarse literalmente en la solicitud de escalado de la herramienta. No
   hace falta pedir una segunda confirmación humana, salvo que una política
   externa la exija. Usar `--admin` solo después del preflight, verificando el
   PR, su motivo de bloqueo y los cambios que se van a promocionar.
8. No borrar `dev` después del merge y conservarla como rama de trabajo activa.
9. Derivar el repositorio desde `origin`; no hardcodear propietario ni nombre.

## Activación

Activar solo cuando el usuario:

- escriba exactamente `git`;
- invoque `$git`;
- o pida inequívocamente ejecutar la publicación completa.

Las operaciones Git normales no activan esta skill.

La activación constituye la autorización explícita descrita en la regla 7 para
la operación completa de publicación.

## Preflight obligatorio

Antes de tocar GitHub o crear un commit, medir y mostrar:

- raíz real del repositorio y rama activa;
- estado del árbol y cambios sin commitear;
- ramas locales, ramas remotas y sus hashes;
- remoto `origin` y repositorio derivado de él;
- worktrees activos;
- existencia de un PR abierto `dev -> main`;
- resultado de las pruebas y comprobaciones relevantes ya ejecutadas.

No asumir que un árbol `0/0` local/remoto tiene el mismo contenido. Comparar
también los árboles Git cuando sea necesario.

## Bloqueo no destructivo por contenido inesperado

Antes de crear el PR y justo antes de fusionarlo, comparar `dev` con `origin/main`
usando el ancestro común. Distinguir:

- cambios nuevos de `dev` que todavía deben promocionarse: permitirlos;
- cambios nacidos en `main` y ausentes o distintos en `dev`: bloquearlos.

Si se activa el bloqueo:

- no borrar, sobrescribir, resetear, reconciliar ni crear una PR automática;
- no ejecutar una promoción parcial;
- conservar el PR abierto si ya existe;
- emitir un informe completo de las diferencias y esperar decisión humana.

Para cada ruta afectada, incluir:

- ancestro común y commits/autores que explican el cambio;
- estado Git, ruta anterior si hubo renombrado, número de líneas y metadatos;
- parche Git completo de la ruta, incluidos sus valores reales;
- tipo de contenido y relevancia para aplicación, tests, instaladores,
  documentación u operación;
- consecuencia concreta de sustituir, restaurar o retirar esa versión;
- recomendaciones no destructivas.

Presentar el diagnóstico en tres niveles:

1. **Agente IA:** datos estructurados y precisos, sin reinterpretar hechos.
2. **Tutor humano senior:** causa, contenido, relevancia, riesgo y opciones.
3. **Bro/junior:** explicación sencilla de qué apareció, por qué no se toca y
   qué decisión humana falta.

No elegir automáticamente entre conservar, reubicar, declarar excepción o
retirar. Cualquier retirada requiere un cambio explícito y revisable mediante
PR.

## Ejecución

Desde la raíz real del repositorio, tras el preflight y la confirmación
correspondiente:

```bash
./scripts/git_ship.sh
./scripts/git_ship.sh "mensaje de commit"
```

Sin mensaje explícito, el script genera uno con la fecha y hora de la sesión.
El script:

1. conserva `dev` como rama de trabajo;
2. añade y commitea los cambios pendientes;
3. publica `dev` en `origin`;
4. crea o reutiliza el PR `dev -> main`;
5. intenta fusionarlo desde GitHub con merge normal y puede repetirlo con
   `--admin` automáticamente si la política de la rama bloquea el merge normal;
6. solo tras confirmación del merge actualiza `main` por fast-forward y vuelve
   a `dev`.

No usar `git merge` local ni hacer push directo a `main`.

## Worktrees

Si `main` está checked out en otro worktree, actualizar esa rama desde su propio
worktree con `git pull --ff-only`. Si el worktree está sucio o la rama ha
divergido, detenerse sin forzar, resetear ni fusionar.

La sincronización local posterior no es una promoción entre ramas y no sustituye
al PR de GitHub.

## GitHub CLI en entornos aislados

`gh auth status` puede informar erróneamente de que el token es inválido dentro
de un entorno aislado que no puede leer el llavero de macOS. No cerrar sesión,
no renovar el token ni concluir que la credencial es inválida por ese resultado.

Si falla dentro del aislamiento:

1. repetir `gh auth status --hostname github.com` fuera del aislamiento;
2. continuar solo si esa comprobación confirma la cuenta activa y el token
   existente;
3. no pedir login ni renovación si la autenticación externa funciona.

## Confirmación final

Informar con mediciones reales:

- rama de trabajo final activa y commit publicado;
- número, URL, estado y commit de merge del PR;
- hashes de `dev`, `origin/dev`, `main` y `origin/main`;
- sincronización local/remota de ambas ramas;
- igualdad final de los árboles de `dev` y `main`, diferenciándola de la
  igualdad de hashes de las referencias;
- estado final del árbol;
- cualquier cambio que haya quedado fuera;
- cualquier bloqueo, requisito de revisión, check o política de GitHub.

Si el PR queda pendiente o alguna comprobación no puede ejecutarse, confirmar
qué acciones sí llegaron a ejecutarse y no afirmar que la publicación terminó.
