# Pendiente: posible integración futura con Thymer

Estado: propuesta no implementada.

Fecha de registro: 2026-08-28.

## Motivo

Se ha evaluado Thymer y `thymercli` como posible complemento futuro de Fuente.
La idea principal no es añadir otro lugar para tomar notas, sino estudiar si
Thymer puede aportar un entorno colaborativo en tiempo real para proyectos de
Fuente y permitir que una IA local trabaje sobre ese contexto compartido.

Por ahora no aporta valor inmediato al flujo actual de Fuente, que ya usa
Markdown, Obsidian, SQLite, ChromaDB y Ollama local. La integración queda
pospuesta hasta que Thymer y sus interfaces sean estables.

## Qué son las piezas

- **Thymer**: espacio de trabajo para notas, tareas, planificación y
  colecciones con vistas de tabla, kanban, galería o calendario.
- **Colaboración de Thymer**: varios usuarios trabajan sobre el mismo
  workspace y Thymer sincroniza sus cambios en tiempo real.
- **`thymercli`**: binario local que ofrece una CLI y un servidor MCP. MCP es
  un protocolo para que agentes como Codex puedan consultar y modificar el
  workspace con permisos explícitos.
- **Markdown Mirror**: mecanismo que refleja el workspace como archivos
  Markdown locales. La página de producto de Thymer lo anuncia como
  bidireccional; el mirror incluido actualmente en `thymercli` está descrito
  como exportación unidireccional, por lo que no deben tratarse como la misma
  garantía.

Fuentes oficiales consultadas:

- [Thymer](https://thymer.com/)
- [Markdown Mirror](https://thymer.com/markdown-mirror)
- [Thymer MCP y CLI](https://thymer.com/mcp)

## Cómo parece que podría lograrse

La colaboración no se conseguiría simplemente compartiendo una carpeta con
archivos `.md`. El diseño probable sería:

1. Cada usuario de Fuente accedería al mismo workspace u organización de
   Thymer.
2. Thymer sería la capa de edición colaborativa en tiempo real para proyectos,
   tareas, comentarios, estados y planificación.
3. Fuente incorporaría un adaptador oficial y estable para leer proyectos y
   cambios de Thymer, proyectarlos en su consola y conservar sus propios
   identificadores, revisiones y trazabilidad.
4. Cuando fuese necesario, Fuente escribiría de vuelta estados o resultados
   mediante una interfaz soportada por Thymer, no editando a ciegas los mismos
   archivos desde varios procesos.
5. La IA local de Fuente, preferentemente Ollama, podría consultar el contexto
   compartido, resumirlo, proponer cambios y devolver tareas o actualizaciones
   después de pasar por la aprobación humana de Fuente.

`thymercli` podría servir como puente para agentes locales mediante MCP, pero su
servidor escucha solo en `127.0.0.1` y no es por sí mismo el backend
multiusuario. Para que Fuente fuese una aplicación colaborativa habría que
separar claramente:

- el backend de sincronización multiusuario de Thymer;
- el adaptador de Fuente para proyectos y cambios;
- el acceso local de la IA mediante MCP o una API estable;
- el flujo editorial de Fuente, que debe conservar aprobación, revisiones,
  hashes y Markdown canónico.

## Lo que no está demostrado todavía

- Que exista una API pública y estable para integrar Fuente directamente con
  Thymer como aplicación.
- Que `thymercli` sea adecuado como dependencia de producción de Fuente.
- Cómo se resolverían conflictos si Fuente y Thymer modificasen el mismo
  Markdown al mismo tiempo.
- Qué parte de la colaboración funcionaría con el mirror de `thymercli`, que
  actualmente se documenta como unidireccional.
- Condiciones definitivas de versión, soporte, despliegue y licencia.

## Criterio para retomarlo

Reabrir este pendiente solo cuando Thymer tenga una versión estable y una
interfaz soportada para integración. Antes de implementarlo habrá que preparar
un diseño pequeño y medible que defina el propietario de cada dato, el sentido
de cada sincronización, la resolución de conflictos, los permisos de la IA y
la conservación de los gates editoriales de Fuente.

La primera prueba debería ser de solo lectura sobre un workspace de prueba:
dos usuarios editando un proyecto en Thymer, Fuente observando los cambios y
Ollama generando un resumen local sin modificar notas canónicas. Solo después
de demostrar sincronización y recuperación segura tendría sentido estudiar la
escritura de vuelta.
