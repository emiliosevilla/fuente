# Reglas de Proyecto Funes

## Protocolo Grill-Me + Goal (`/grill-me-goal` o `/grill-me`) — SOLO BAJO PETICIÓN EXPLÍCITA (EXACTAMENTE 7 ITERACIONES)

El protocolo **/grill-me-goal** (o **/grill-me**) **NUNCA se ejecutará por defecto**. Únicamente se activará cuando el usuario invoque **EXPRÉSAME Y EXPLÍCITAMENTE** el comando slash `/grill-me-goal` o `/grill-me` en su mensaje.

---

### 🔄 Bucle Progresivo de 7 Iteraciones Exactas sobre el Mismo Objetivo (`Entrevista 7 PreguntasN ➔ PlanificaciónN ➔ Autocrítica HeptapartitaN`)

Cuando el usuario active el comando `/grill-me-goal`, el agente completará **EXACTAMENTE 7 iteraciones progresivas** de profundización técnica focalizadas en el **mismo objetivo inicial que haya definido el usuario en su prompt**. Las iteraciones no tienen temas predefinidos de antemano; en cada iteración se profundiza sobre el objetivo del usuario.

En **TODAS y cada una de las 7 iteraciones (de la Iteración 1 a la 7)**, la estructura obligatoria es:

1. **Entrevista Heptapartita (7 Preguntas)**: Formulación interactiva de **7 Preguntas** (`ask_question`), abordando obligatoriamente una perspectiva por cada uno de los 7 roles sobre el objetivo del ciclo.
2. **Planificación Progresiva (`implementation_plan.md`)**: Refinamiento y expansión del plan de implementación enfocado en el objetivo.
3. **Autocrítica Heptapartita**: Evaluación crítica desde los 7 roles para nutrir la siguiente iteración.

Tras completar la **Iteración 7** con el Veredicto 100% Favorable, se iniciará la ejecución de código de producción.

---

### 🛡️ Roles de la Entrevista y Autocrítica Heptapartita (7 Preguntas por Iteración)
En cada iteración, tanto la Entrevista como la Autocrítica evalúan obligatoriamente estas 7 perspectivas sobre el objetivo del usuario:

1. **Modo Escéptico y Honesto**: Cuestiona la validez de premisas, datos, métricas y asunciones.
2. **Modo Advisor Senior**: Evalúa arquitectura, patrones de diseño, mantenibilidad y rendimiento a largo plazo.
3. **Modo Sabotaje Adversarial**: Busca vectores de fallo, condiciones de carrera, errores E/S y edge cases destructivos.
4. **Modo Fashion**: Evalúa la estética UI, experiencia visual, diseño estéticamente agradable e intuitividad.
5. **Modo Seguridad**: Identifica vulnerabilidades, inyecciones, fugas de datos y vectores de ataque.
6. **Modo Legal**: Inspecciona el cumplimiento de protocolos de privacidad y protección de datos (GDPR/LOPD).
7. **Modo Bad-Beta**: Evalúa la experiencia de usuario cero fricción, guiado simple y tolerancia a errores para personas sin conocimientos informáticos.

---

### 🛡️ Autorización Git global del propietario (2026-08-15)
- El propietario autoriza operaciones Git normales de lectura y escritura, incluidos `git add`, `commit`, `push` no forzado, `pull`, ramas, `merge`, PRs y publicación ordinaria.
- No exigir `/git` como permiso adicional para esas operaciones. El workflow `/git` y `./scripts/git_ship.sh` son atajos para una cascada concreta de publicación.
- Se mantienen los bloqueos automáticos globales para `reset --hard`, `clean -f`, `push --force`, refspecs forzados, `filter-branch`, `filter-repo`, rebase interactivo, `branch -D` y `git rm` sin `--cached`.
- Antes de una operación destructiva, medir el repositorio y el objetivo exacto y comunicar la consecuencia.

### 🔀 Regla obligatoria de PR para merges entre ramas (2026-08-15)
- Todos los merges entre ramas deben hacerse mediante un Pull Request.
- No ejecutar `git merge` directo entre ramas salvo orden explícita del propietario.
- Para promover `dev` a `main`: publicar `dev`, abrir el PR `dev → main`, fusionarlo desde GitHub y volver a `dev`.
