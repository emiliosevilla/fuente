# Reglas de Proyecto Funes

## Protocolo de Entrevista Heptapartita (7 Preguntas), Planificación Progresiva Bucle-Goal y Autocrítica Adversarial (Default Grill-Me + Goal)

A menos que el mensaje del usuario sea explícitamente un comando slash (como `/git`, `/schedule`, `/learn`, etc.), el agente debe tratar CUALQUIER solicitud, propuesta o tarea como si incluyera implícitamente las directivas **/grill-me** y **/goal** con un rango obligatorio de **mínimo 5 y máximo 10 iteraciones**:

---

### 🔄 Bucle Progresivo de 5 a 10 Iteraciones (`Entrevista 7 PreguntasN ➔ PlanificaciónN ➔ Autocrítica HeptapartitaN`)

El agente no escribirá código de producción hasta haber completado como mínimo **5 iteraciones progresivas** de profundización técnica. **En TODAS y cada una de las iteraciones (desde la Iteración 1 hasta la Iteración 10), la entrevista constará obligatoriamente de 7 Preguntas** (`ask_question`), una por cada uno de los 7 roles/perspectivas:

1. **Iteración 1 (Arquitectura General y Diagnóstico 7 Roles)**:
   - Entrevista inicial de **7 Preguntas** (`ask_question`) abordando los 7 roles sobre la propuesta inicial.
   - Redacción inicial de `implementation_plan.md`.
   - Autocrítica Heptapartita (7 Cuestiones: Escéptico, Senior Advisor, Sabotaje Adversarial, Fashion, Seguridad, Legal, Bad-Beta).

2. **Iteración 2 (Detalle Técnico y Estructuras)**:
   - Entrevista de **7 Preguntas** (`ask_question`) derivada directamente de las 7 cuestiones de la Autocrítica Heptapartita previa.
   - Expansión del plan hacia componentes que parecían sólidos para detallar firmas, clases y módulos.
   - Autocrítica Heptapartita sobre rendimiento y legibilidad.

3. **Iteración 3 (Edge Cases, Concurrencia y Resiliencia)**:
   - Entrevista de **7 Preguntas** basada en la Autocrítica Heptapartita de la iteración anterior.
   - Expansión hacia manejo de errores E/S, concurrencia, red (SharePoint/OneDrive), límites de memoria RAM e insumos corruptos.
   - Autocrítica Heptapartita sobre robustez y tolerancia a fallos.

4. **Iteración 4 (Estrategia de Pruebas y Cobertura)**:
   - Entrevista de **7 Preguntas** sobre validación, seguridad y prevención de regresiones.
   - Expansión hacia diseño de pruebas unitarias, fixtures sintéticos con `tempfile` y aislamiento con `unittest.mock`.
   - Autocrítica Heptapartita sobre cobertura de tests.

5. **Iteración 5 (Empaquetado, Portabilidad y Compatibilidad Multiplataforma)**:
   - Entrevista de **7 Preguntas** de integración, usabilidad y legalidad/despliegue.
   - Expansión hacia scripts de build (`build_installer.py`), rutas relativas, `pyinstaller` y ejecución multiplataforma (macOS/Windows).
   - Autocrítica Heptapartita de cierre.

6. **Iteraciones 6 a 10 (Opcionales de Cierre)**:
   - En cada iteración continuada (6 a 10), mantener la **Entrevista de 7 Preguntas** y la **Autocrítica Heptapartita** hasta lograr el **Veredicto 100% Favorable** o alcanzar el **CAP de 10 iteraciones**.

---

### 🛡️ Roles de la Autocrítica y Entrevista Heptapartita (7 Preguntas por Iteración)
En TODA iteración (de la 1 a la 10), tanto la Entrevista como la Autocrítica evalúan obligatoriamente estas 7 perspectivas:

1. **Modo Escéptico y Honesto**: Cuestiona la validez de cada premisa, dato o asunción.
2. **Modo Advisor Senior**: Evalúa diseño, patrones, mantenibilidad y rendimiento a largo plazo.
3. **Modo Sabotaje Adversarial**: Trata de romper activamente el diseño buscando vectores de fallo, ambigüedades y edge cases.
4. **Modo Fashion**: Aporta el punto de vista de la funcionalidad, intuitividad, user-friendly UI y diseño estéticamente agradable.
5. **Modo Seguridad**: Aporta el punto de vista del "hacker bueno", responsable de ciberseguridad, experto en encontrar formas de crackear, filtrar, romper barreras de seguridad y forzar o aprovechar leaks existentes o potenciales.
6. **Modo Legal**: Aporta el punto de vista del inspector de protocolos de protección de datos y privacidad (GDPR/LOPD).
7. **Modo Bad-Beta**: Aporta el punto de vista del usuario al que, de entrada, no le gusta la informática, necesita guiado, no entiende palabras técnicas y no es capaz de hacer prácticamente nada si no es tan fácil como para un niño de 5 años.

---

### 🛡️ Regla Estricta de Control de Publicación Git
- **PROHIBICIÓN DE EJECUCIÓN PROACTIVA**: El agente NUNCA debe ejecutar `./scripts/git_ship.sh`, `git commit` o el workflow `/git` por iniciativa propia tras completar un plan, tarea o conjunto de pruebas.
- **SOLO BAJO PETICIÓN EXPLÍCITA**: La publicación Git únicamente se ejecutará cuando el usuario introduzca expresamente el comando `/git`.

---

### ⚡ Excepción para Comandos Slash
- Si la entrada del usuario inicia explícitamente con un comando slash (ej. `/git`), ejecuta de forma inmediata la habilidad asociada sin activar este protocolo.
