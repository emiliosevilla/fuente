# Fuente — Plan de migración canónica, nombre y sistema Nord

**Estado:** hoja de ruta vigente. El SDD detallado de ejecución es
[`2026-08-14-fuente-execution-sdd.md`](2026-08-14-fuente-execution-sdd.md).
Este documento no autoriza por sí solo cambios de código, Vault, GitHub ni Git.

**Especificación rectora:**
[`2026-08-14-fuente-canonical-record-and-terminology.md`](../specs/2026-08-14-fuente-canonical-record-and-terminology.md).

**Objetivo:** convertir el producto Funes en Fuente sin perder documentos ni
romper su trazabilidad; hacer que `3_limpio` sea el único registro canónico
aprobado y que `4_salida/Sumarios` sea contenido derivado con orígenes
verificables; aplicar un sistema visual propio basado en la paleta Nord.

**Regla de orden:** no se renombra el repositorio ni se mueven carpetas hasta
que la validación de aprobación de `3_limpio` y la lectura compatible estén
medidas. Cada fase termina con pruebas y un punto de revisión humana.

## Fase 0A — Benchmark de `qwen3.5:0.8b` para RAM ultra-ligera

`qwen3.5:0.8b` es el candidato predeterminado para Auto en equipos con menos
de 8 GB de RAM, pero no se activa como selección efectiva hasta que complete
esta fase. `Eco estricto` permanece deliberadamente en BM25 sin LLM.

1. Añadir el modelo al catálogo con una estimación de memoria conservadora,
   `num_ctx=4096` y concurrencia uno. La selección automática debe exigir que
   el nombre exacto esté instalado; nunca puede provocar una descarga.
2. Mantener `qwen2.5:0.5b` como alternativa de compatibilidad y BM25 como
   degradación cuando ningún modelo satisfaga la holgura de RAM medida.
3. Ejecutar el benchmark, en el equipo de menos de 8 GB, con una muestra fija
   de documentos aprobados de `3_limpio`. Comparar `qwen3.5:0.8b` con
   `qwen2.5:0.5b` usando los mismos prompts y límites de salida.
4. Medir para cada ejecución: memoria disponible antes, durante y después;
   latencia; longitud de salida; errores; validación estructural; y fidelidad
   al origen. La fidelidad se revisa contra los documentos aprobados, no contra
   el sumario generado.
5. Promoverlo a la selección efectiva solo si conserva el margen de seguridad
   configurado del 35 %, no fuerza descarga ni intercambio de memoria evitable,
   y no empeora la validación ni la fidelidad respecto de `qwen2.5:0.5b`.

**Pruebas de salida:** selección solo de modelo instalado; contexto de 4.096
tokens y concurrencia uno; rechazo o BM25 con memoria insuficiente; resultados
reproducibles del benchmark; salida que conserva estructura y orígenes. La
promoción final requiere revisión humana de la evidencia medida.

## Fase 0 — Inventario y protección de la migración

1. Medir todas las apariciones de `Funes`, `funes`, `.funes`, `Fuentes`,
   `source`, `sources` y `source_kind`, agrupándolas en: identidad del
   producto, API/serialización, rutas de Vault, almacenamiento, UI, pruebas,
   ejemplos y documentación histórica.
2. Medir el contenido real de cada `3_limpio`, su estado de frontmatter y los
   sumarios presentes en `4_salida`. No inferir que una nota está aprobada por
   su ubicación.
3. Diseñar un manifiesto de migración con precondiciones, rutas antiguas y
   nuevas, hashes, resultado, fecha y modo de recuperación. Bloquear
   colisiones, enlaces simbólicos, cambios humanos y recorridos fuera del
   Vault.
4. Presentar a la persona responsable el inventario y la muestra de cambios
   antes de aplicar cualquier movimiento.

**Pruebas de salida:** inventario reproducible; simulación sin escritura;
ninguna ruta externa al Vault aceptada; manifiesto que permite reanudar tras
interrupción.

## Fase 1 — Registro canónico y aprobación de `3_limpio`

1. Crear un registro de aprobaciones reconstruible desde Markdown y un
   manifiesto local de revisión. Su clave es `note_id + revision + content_hash`.
   Debe guardar revisor y fecha, pero no introducir una segunda copia del
   documento.
2. Añadir operaciones explícitas: solicitar aprobación, aprobar la revisión,
   invalidar por cambio y consultar elegibilidad. El editor debe avisar que
   modificar un documento aprobado crea una revisión sin aprobar.
3. Cambiar los servicios de generación, fusión, reflow y exportación para que
   resuelvan primero los documentos aprobados de `3_limpio`. Una solicitud con
   un origen no aprobado falla de forma explicable y sin escribir en
   `4_salida`.
4. Añadir a cada derivado una lista tipada de orígenes: identidad, revisión,
   hash y ruta de presentación. La ruta no es la identidad ni la autorización.
5. Ajustar el corpus RAG y el grafo para distinguir contenido canónico de
   contenido derivado. Los resultados que exponen una afirmación deben poder
   devolver los orígenes aprobados; los sumarios solo mejoran la navegación.

**Pruebas de salida:**

- no se crea ni actualiza un sumario desde una revisión sin aprobar;
- editar un origen aprobado lo invalida y marca sus derivados;
- el mismo texto con revisión o hash distinto no satisface una aprobación
  anterior;
- borrar catálogo, grafo e índice no altera `3_limpio` y permite reconstruir;
- la API y el bridge no exponen rutas absolutas ni permiten aprobar por un ID
  de ruta falsificado.

**Punto humano:** revisar un documento, aprobarlo, modificarlo y comprobar que
el sistema bloquea la generación hasta una nueva aprobación.

## Fase 2 — Migración de vocabulario editorial

1. Definir schema v3 compatible: `note_type: summary`, `origin_kind` y
   `origins`. El lector v3 acepta temporalmente `source`, `source_kind` y
   `sources`, los normaliza en memoria y nunca los vuelve a escribir.
2. Migrar de modo explícito los frontmatters v2 mediante manifiesto, sin
   reescribir cuerpos Markdown. Conservar `note_id`, revisiones, hashes,
   enlaces y aprobaciones.
3. Cambiar DTOs, catálogo SQLite, consultas, contratos de bridge, nombres de
   formularios y textos de interfaz. Las carpetas de entrada montada pasan a
   llamarse proveedores o entradas, nunca orígenes.
4. Convertir los valores antiguos de clasificador y plantillas en los tipos de
   sumario definidos; no clasificar automáticamente los elementos
   `Sin_clasificar` si no hay evidencia suficiente.
5. Retirar la compatibilidad de lectura solo después de medir que no quedan
   documentos ni clientes que la requieran.

**Pruebas de salida:** lectura v2 y v3 durante la transición; escritura solo
v3; migración idempotente; rechazo de `origin_kind` fuera de un sumario;
preservación de los orígenes y de las revisiones aprobadas.

## Fase 3 — Estructura física del Vault

1. Calcular en seco el traslado de `4_salida/Fuentes/` a
   `4_salida/Sumarios/`, preservando subtipos y sin mover `3_limpio`.
2. Actualizar MOC, enlaces de carpeta, vistas Obsidian y rutas de recuperación
   por `note_id`, no por sustitución textual ciega.
3. Aplicar solo los movimientos incluidos en el manifiesto aprobado. Una nota
   editada desde el cálculo queda fuera y se informa para revisión humana.
4. Revalidar que cada sumario conserva sus orígenes aprobados, que no hay
   colisiones y que los alias de rutas antiguas resuelven durante la ventana de
   compatibilidad.

**Pruebas de salida:** dry-run sin escritura; apply reanudable; rollback seguro
en notas no editadas; RAG, grafo, lector y exportación encuentran el mismo
`note_id`; las notas derivadas se regeneran desde `3_limpio`.

**Punto humano:** aprobar la vista previa de destinos antes de cualquier
movimiento físico.

## Fase 4 — Cambio completo de Funes a Fuente

1. Hacer una segunda simulación que enumere todos los cambios de identidad:
   paquete Python, puntos de entrada, configuración, `.funes` a `.fuente`,
   recibos, datos locales, textos, ejemplos, `Vault_Funes` y referencias de
   documentación.
2. Introducir una migración única de configuración y estado local de `.funes`
   a `.fuente`, con copia de seguridad, hashes y recuperación. No mantener dos
   directorios activos después de la migración.
3. Renombrar el paquete y sus importaciones de forma atómica en el mismo
   cambio; actualizar los comandos de instalación y las pruebas. No crear un
   alias permanente `funes` para ocultar errores de conversión.
4. La persona responsable renombra el repositorio y sus integraciones remotas
   cuando la simulación local, las pruebas y la documentación estén aprobadas.
   Esta operación no la ejecuta el agente.
5. Actualizar el contenido histórico solo con notas de procedencia cuando sea
   necesario explicar nombres antiguos. El contenido vigente usa Fuente.

**Pruebas de salida:** instalación limpia de Fuente; actualización de un Vault
Funes existente sin pérdida; arranque, migración y rollback medidos; búsqueda
sin apariciones nuevas de los nombres antiguos fuera de la compatibilidad
declarada; documentación y comandos coherentes.

**Punto humano:** aprobar el inventario final y realizar el cambio de
repositorio/remoto por separado.

## Fase 5 — Sistema visual Fuente basado en Nord

1. Crear un fichero de tokens propio, con nombres semánticos `--fuente-*`, a
   partir de los valores medidos de Polar Night, Snow Storm, Frost y Aurora.
   No copiar todo `nord/`; si se copia código, incorporar sus avisos Apache-2.0.
2. Sustituir colores directos de la consola por tokens. Crear componentes CSS
   reutilizables para superficies, botones, campos, modales, badges, estados
   de trabajo y nodos/aristas del grafo.
3. Aplicar primero los tokens al lector de tres paneles, donde el contraste y
   la jerarquía de información son más importantes: nota; propiedades;
   relaciones locales.
4. Revisar foco de teclado, contraste de texto, error/éxito sin depender solo
   del color, navegación en pantalla estrecha y `prefers-reduced-motion`.
5. Mantener los sinks DOM seguros y CSP existentes: el cambio visual no puede
   reintroducir HTML sin validar ni recursos externos.

**Pruebas de salida:** contratos de consola existentes; test estático que evita
colores directos fuera de los tokens; navegación por teclado; lector adaptable
sin perder paneles; comprobación humana visual en el launcher nativo.

## Fase 6 — Cierre y retirada de compatibilidad

1. Ejecutar las pruebas focalizadas de aprobación, migración, Vault, RAG,
   grafo, bridge y consola; después, la suite y el release gate actuales.
2. Actualizar `task.md`, README, especificaciones, ayuda de interfaz y guía de
   migración con resultados medidos, no previsiones.
3. Conservar el manifiesto final y una guía de recuperación. Retirar campos,
   alias y rutas antiguas únicamente tras una nueva medición de ausencia y un
   punto humano explícito.

**Resultado final:** Fuente presenta una biblioteca coherente: los Markdown
aprobados de `3_limpio` sostienen cualquier afirmación; `Sumarios` y demás
notas son derivados rastreables; el nombre no se mezcla con la procedencia; y
la interfaz usa un sistema visual consistente y accesible.
