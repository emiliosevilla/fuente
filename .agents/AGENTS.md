# Reglas de Proyecto Funes

## Protocolo de Entrevista, Planificación Progresiva Bucle-Goal y Autocrítica Adversarial (Default Grill-Me + Goal)

A menos que el mensaje del usuario sea explícitamente un comando slash (como `/git`, `/schedule`, `/learn`, etc.), el agente debe tratar CUALQUIER solicitud, propuesta o tarea como si incluyera implícitamente las directivas **/grill-me** y **/goal** con un rango obligatorio de **mínimo 5 y máximo 10 iteraciones**:

---

### 🔄 Bucle Progresivo de 5 a 10 Iteraciones (`PlanificaciónN ➔ EntrevistaN ➔ AutocríticaN`)

El agente no escribirá código de producción hasta haber completado como mínimo **5 iteraciones progresivas** de profundización técnica:

1. **Iteración 1 (Arquitectura General)**:
   - Entrevista de diseño inicial (`ask_question`, de una en una con `(Recomendada)`).
   - Redacción inicial de `implementation_plan.md`.
   - Autocrítica Tripartita (Escéptico, Senior Advisor, Sabotaje Adversarial).

2. **Iteración 2 (Detalle Técnico y Estructuras)**:
   - Expansión del plan hacia componentes que parecían sólidos para detallar firmas, clases y módulos.
   - Entrevista sobre decisiones de estructuras de datos y tipos.
   - Autocrítica Tripartita sobre rendimiento y legibilidad.

3. **Iteración 3 (Edge Cases, Concurrencia y Resiliencia)**:
   - Expansión hacia manejo de errores E/S, concurrencia, red (SharePoint/OneDrive), límites de memoria RAM e insumos corruptos.
   - Entrevista sobre estrategias de fallback y tolerancia a fallos.
   - Autocrítica Tripartita sobre robustez.

4. **Iteración 4 (Estrategia de Pruebas y Cobertura)**:
   - Expansión hacia diseño de pruebas unitarias, fixtures sintéticos con `tempfile` y aislamiento con `unittest.mock`.
   - Entrevista sobre validación y prevención de regresiones.
   - Autocrítica Tripartita sobre cobertura de tests.

5. **Iteración 5 (Empaquetado, Portabilidad y Compatibilidad Multiplataforma)**:
   - Expansión hacia scripts de build (`build_installer.py`), rutas relativas, `pyinstaller` y ejecución multiplataforma (macOS/Windows).
   - Entrevista final de integración.
   - Autocrítica Tripartita de cierre.

6. **Iteraciones 6 a 10 (Opcionales de Cierre)**:
   - Si tras la Iteración 5 se detectan riesgos no resueltos, continuar el bucle hasta lograr el **Veredicto 100% Favorable** o alcanzar el **CAP de 10 iteraciones**.

---

### 🛡️ Roles de la Autocrítica Tripartita (En cada iteración)
- **Modo Escéptico y Honesto**: Cuestiona la validez de cada premisa, dato o asunción.
- **Modo Advisor Senior**: Evalúa diseño, patrones, mantenibilidad y rendimiento a largo plazo.
- **Modo Sabotaje Adversarial**: Trata de romper activamente el diseño buscando vectores de fallo, ambigüedades y edge cases.

### ⚡ Excepción para Comandos Slash
- Si la entrada del usuario inicia explícitamente con un comando slash (ej. `/git`), ejecuta de forma inmediata la habilidad asociada sin activar este protocolo.
