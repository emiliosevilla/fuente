# Reglas de Proyecto Funes

## Protocolo de Entrevista de Diseño Automático (Default Grill-Me)

A menos que el mensaje del usuario sea explícitamente un comando slash (como `/git`, `/schedule`, `/learn`, etc.), el agente debe tratar CUALQUIER solicitud, propuesta o tarea como si incluyera implícitamente la directiva **/grill-me**:

1. **Entrevista de Diseño**: Antes de realizar modificaciones de código, arquitectura o flujos de trabajo, entrevista al usuario sobre cada rama de decisión hasta alcanzar un entendimiento completo y compartido.
2. **Preguntas de Una en Una**: Plantea las preguntas de **una en una** utilizando la herramienta interactiva `ask_question`.
3. **Respuesta Recomendada**: En cada opción presentada en `ask_question`, proporciona siempre tu respuesta recomendada prefijada con `(Recomendada)`.
4. **Inspección Previa del Código**: Si una pregunta puede ser respondida o aclarada leyendo el código base, explora primero con herramientas de búsqueda/lectura antes de formular la pregunta.
5. **Excepción de Comandos Slash**: Si la entrada del usuario inicia explícitamente con un comando (por ejemplo, `/git`), ejecuta de forma inmediata el flujo o skill asociado sin activar la entrevista `/grill-me`.
