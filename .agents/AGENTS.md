# Reglas de Proyecto Funes

## Protocolo de Entrevista, Planificación Bucle-Goal y Autocrítica Adversarial (Default Grill-Me + Goal)

A menos que el mensaje del usuario sea explícitamente un comando slash (como `/git`, `/schedule`, `/learn`, etc.), el agente debe tratar CUALQUIER solicitud, propuesta o tarea como si incluyera implícitamente las directivas **/grill-me** y **/goal**:

### 1. Entrevista de Diseño Inicial (`/grill-me`)
- Antes de modificar código o arquitectura, explora primero la base de código.
- Entrevista al usuario sobre cada rama de decisión utilizando la herramienta `ask_question` planteando las preguntas **de una en una**.
- En cada opción presentada, incluye siempre la alternativa recomendada prefijada con `(Recomendada)`.

### 2. Elaboración del Plan de Implementación (`implementation_plan.md`)
- Con las respuestas de la entrevista, redacta el artefacto `implementation_plan.md` detallando la arquitectura, cambios propuestos y plan de verificación.

### 3. Bucle Autónomo de Autocrítica Adversarial e Iteración (`/goal` - Máximo 10 Iteraciones)
El agente debe actuar en un bucle iterativo donde su objetivo implícito (`/goal`) es alcanzar un **Veredicto 100% Favorable** sobre el plan antes de escribir código de producción.

Para cada iteración (hasta un **máximo de 10 iteraciones**):
1. **Autocrítica Tripartita**: Analiza el `implementation_plan.md` bajo 3 roles estrictos:
   - **Modo Escéptico y Honesto**: Cuestiona cada premisa, validez de datos y asunciones no probadas.
   - **Modo Advisor Senior**: Evalúa mantenibilidad, patrones de diseño, rendimiento y escalabilidad a largo plazo.
   - **Modo Sabotaje Adversarial**: Busca activamente vectores de fallo, ambigüedades, dependencias frágiles, edge cases y riesgos de ejecución.
2. **Evaluación de Hallazgos**:
   - Si se descubren puntos débiles, riesgos o dudas:
     a) Plantea una nueva ronda de entrevista (`ask_question`) centrada en los hallazgos críticos.
     b) Refina y actualiza el artefacto `implementation_plan.md`.
     c) Incrementa el contador de iteración y repite la autocrítica tripartita.
   - Si el veredicto es **100% Favorable** sin riesgos ni ambigüedades detectadas, o si se alcanza la **iteración 10 (CAP máximo)**:
     - Presenta la autocrítica final y solicita la aprobación del usuario para proceder a la ejecución.

### 4. Excepción para Comandos Slash
- Si la entrada del usuario inicia explícitamente con un comando slash (por ejemplo, `/git`), ejecuta de forma inmediata el flujo o skill asociado sin activar este protocolo.
