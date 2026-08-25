# SDD: prueba_real de Fuente

## Objetivo

Validar la versión publicada de Fuente en dos niveles: primero desde el repositorio y después como instalación real de usuario. El resultado debe separar qué funciona, qué funciona sólo bajo condiciones concretas y qué no está implementado.

Este SDD no añade funcionalidades de producto. Organiza construcción de artefactos, instalación, pruebas de aceptación y registro de resultados.

## Estado vigente — 2026-08-25

Campaña real ejecutada sobre `/Applications/Fuente.app`, sin Chrome, con Vault
autorizado en `/Users/emiliosevillaortego/Desktop/Nuevo Vault`.

- `PASS`: arranque, detección de Obsidian, selección y persistencia de Vault,
  ETL real, aprobación, procesamiento, exportación, lector, WYSIWYG, cola,
  Salud, audio Tiny local y handoff a Meetily.
- `PARTIAL`: Meetily no tiene bridge embebido distribuido; Windows,
  OneDrive/SharePoint montado y motores/modelos no instalados no se declaran
  probados.
- Resultado global: `R REAL: PARTIAL`. No convertir límites de entorno en
  fallos silenciosos ni `NOT_RUN` histórico en `PASS`.
- Informe vigente:
  `docs/superpowers/reports/2026-08-25-prueba-real-final.md`.

### Cierre vigente post-corrección de reintento — 2026-08-25

La build instalada final se probó en `/Applications/Fuente.app`, sin Chrome,
con el Vault real `/Users/emiliosevillaortego/Desktop/Nuevo Vault`.

- El PASO 2 se pulsó sobre la tarjeta visible de Transcripción.
- El mismo audio reintroducido con otro nombre conservó el hash
  `1da7c0e79751df1714b92610a89a687a881dd8ebda88ebaaec5fa1d443f8ca37`.
- Resultado: job `043166d2-9a0d-4179-bf38-50ccc51b44ca` en
  `saved_clean / pending / awaiting_clean_approval`, intento `1`.
- Se creó `3_capturado/QA_Reintroducido_Audio_Final2_20260825.md`, SHA-256
  `2eff32839f3ef071e5f01b1f405880a682c5eb8dd3988a6520dd8c0f106374b7`.
- El original salió de `1_volcado`; no apareció una cuarentena `Final2`.
- El fix de consola evita llamar a `resume()` para jobs terminales. El watcher
  mantiene la misma protección en el flujo automático.

Artefactos instalados medidos:

- DMG: `32.085.275` bytes, SHA-256
  `29d529831620932b68dbffb269bc720d8da9561cdeb5ca8d6b822d6a5c6aa33b`.
- ZIP: `32.464.912` bytes, SHA-256
  `d6602034e07fc654714116bc0799ea767e21598a5e2fd605fce5752c55c5b33e`.

Evidencia visual: `/tmp/fuente-final-fix-startup.png` y
`/tmp/fuente-step2-final2-quartz-logical.png`. Informe:
`docs/superpowers/reports/2026-08-25-prueba-real-final.md`.

## Baseline

- Repositorio: fuente.
- Rama publicada: dev, integrada en main mediante PR #64.
- Commit de código bajo prueba: e6aef697a6f9b4f49f1878940b95f8cf51d2b342; merge publicado: a44aa0a92f2231bad7a401be30bca159fec45910.
- Empaquetado: build_installer.py y fuente.spec.
- Instaladores: instalar_fuente.command y instalar_fuente.bat.
- Vault de prueba autorizado: /Users/emiliosevillaortego/Documents/Programación/fuente_vault.
- Tema inicial: General.
- Suite histórica: 1336 passed, 1 skipped, 1 warning.
- Release gate histórico: RESULT: READY.

La suite histórica no sustituye pruebas de instalación, micrófono, permisos, rutas montadas ni comportamiento visual manual.

## Reinicio activo de campaña — 2026-08-23

Se reinicia la campaña completa desde PR-00 sin borrar ni reinterpretar la evidencia histórica. Baseline activo medido: rama `dev`, commit `e6aef697a6f9b4f49f1878940b95f8cf51d2b342`; merge publicado en `main`: `a44aa0a92f2231bad7a401be30bca159fec45910`; PR #64.

Estado activo inicial de la campaña: todas las fases estaban `NOT_RUN`. Estado actual: PR-00 y PR-05 tienen `S PASS`, `R PASS` y están `COMPLETE`; PR-04 tiene `S PASS`, `R PARTIAL` y está `PARTIAL`; PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11 y PR-02 tienen `S PASS`, `R NOT_RUN` y están `PARTIAL`; PR-12 tiene `S PASS`, `R NOT_RUN` y está `PARTIAL`. La campaña global está `PARTIAL`. El orden obligatorio es: PR-00, PR-04, PR-05, PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11, PR-02, PR-12. Cada fase ejecuta primero `S` sintética y sólo si pasa ejecuta `R` real.

`PR-10` repite su prueba sintética y no hereda automáticamente el bloqueo histórico por IDs duplicados. En el estado actual PR-00 y PR-05 están `COMPLETE`; PR-04 está `PARTIAL` (`S PASS`, `R PARTIAL`); PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11 y PR-02 están `PARTIAL` (`S PASS`, `R NOT_RUN`); PR-12 está `PARTIAL` (`S PASS`, `R NOT_RUN`).

### Evidencia vigente de PR-12 S — 2026-08-24

Se realizó sólo auditoría documental y `git diff --check`, sin repetir suites completas.
Se comprobó el estado S/R documentado y la trazabilidad de informes para PR-00, PR-04, PR-05,
PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11 y PR-02. Los estados
`NOT_RUN` se conservaron. PR-12 S = `PASS`; PR-12 R = `NOT_RUN`; global =
`PARTIAL`. Informe: `docs/superpowers/reports/2026-08-24-prueba-real-synthetic-and-real-script.md`.

### Histórico — evidencia anterior de PR-02 S — 2026-08-24

La suite portable de distribución Windows pasó `132 passed in 4.16s` en
macOS. Cubre contrato y scripts del instalador, package data, autorización de
rutas con `PureWindowsPath`, descubrimiento parametrizado para `win32`,
gobernador de RAM y system checker. `build_installer.py` y `fuente.spec`
pasaron compilación sintáctica y checks estáticos de nombres de artefacto,
scripts por plataforma y recursos requeridos. Host medido: macOS 26.6 arm64,
Python 3.14.6. `PR-02 S = PASS`; `PR-02 R = NOT_RUN`; estado `PARTIAL`.
No se simula Windows ni se declara construido un `.exe`.

### Addendum de evidencia instalada — 2026-08-25

La prueba real del paquete macOS se amplió con el Vault autorizado
`/Users/emiliosevillaortego/Desktop/Nuevo Vault`. El flujo B se completó desde
la aplicación instalada: aprobación canónica, procesamiento a `4_procesado`,
aprobación independiente de salida, compartición a `5_compartido` y
publicación de discusión visible. El job quedó `completed`; la salida y el
destino conservaron el hash
`1bff7530306930332c710b79886e8c6c6403317f7f67a0b4dd1d6bc146ef9589`, y las
tablas `processed_approvals` y `shared_outputs` registraron revisión 3.

La aplicación instalada también mostró el contador corregido
`Archivos Procesados: 4`. La corrección elimina la lectura de la ruta antigua
`.fuente_processed` y cuenta las notas Markdown reales de `4_procesado`, sin
contar el MOC.

La campaña sigue `PARTIAL`: la discusión se publicó, pero esta sesión de
automatización no valida de forma independiente el campo de autor porque el
texto introducido terminó duplicado en autor y comentario. Meetily, Windows,
OneDrive/SharePoint y los motores opcionales siguen sin cierre real. El
spinner del instalador y el cierre automático de Terminal siguen siendo
peticiones pendientes.

### Histórico — evidencia anterior de PR-03 S — 2026-08-24

`instalar_fuente.command` ya no crea accesos antes del asistente; `step_create_shortcuts` falla si `create_shortcuts` devuelve `False`. El probe sintético desde el ZIP limpio creó dos `.command` ejecutables con `target_dir` explícito, sin selector Tk, y ejecutó `run_installation(..., create_shortcuts=False, install_model=False)` con las cinco raíces canónicas. Los focales del instalador dieron `23 passed`; `PR-03 S = PASS`, `PR-03 R = NOT_RUN`, estado `PARTIAL`. Evidencia completa: `.superpowers/sdd/2026-08-23-prueba-real/task-PR-03-S-report.md`. No se ejecutaron extras, modelos ni Vault real.

### Histórico — evidencia anterior de PR-10 S — 2026-08-24

La suite focal de Vault y migraciones pasó `134 passed in 3.76s` sobre
temporales sintéticos. Cubre dry-run, plan-id, hashes, apply, rollback,
idempotencia, conflictos humanos, symlinks, autorización de rutas, IDs
duplicados y CLI. Se corrigió el guard canónico de `3_capturado` en
`taxonomy_migration.py`; el resto del cambio fue de fixtures y documentación.
`PR-10 S = PASS`, `PR-10 R = NOT_RUN`, estado `PARTIAL`. Evidencia completa:
`.superpowers/sdd/2026-08-23-prueba-real/task-PR-10-S-report.md`.

## Tutor y bro

- Automatizado: prueba ejecutable sin intervención humana.
- Instalación real: Fuente se instala desde un paquete limpio, no desde checkout.
- Aceptación: persona ejecuta acción y confirma resultado visible y archivos.
- NOT_RUN: todavía no se ha probado; no significa funciona ni falla.
- BLOCKED: no puede probarse hasta resolver dependencia o decisión.
- DEPLOYED: instalación o ejecución real medida.

Versión bro: primero comprobamos motor en laboratorio; después instalamos como usuario y comprobamos que no se rompe fuera del laboratorio.

## Capacidades ya cubiertas por código y tests; comprobar igualmente

1. Layout por tema: 1_volcado/personal, 1_volcado/común, 2_copiado, 3_capturado, 4_procesado, 5_compartido.
2. Autorización de rutas y contención dentro del tema activo.
3. Migración con inventario, hashes, apply, verify y rollback.
4. MarkItDown como primera extracción local.
5. Docling como escalada para PDF e imagen difíciles.
6. Auditoría de extracción, reintentos y cuarentena.
7. BM25 como fallback local.
8. MiniRAG como backend primario local, fijado y con procedencia.
9. ChromaDB sólo como backend de refinamiento.
10. Aprobaciones ligadas a document_id, revisión y hash.
11. Refinamiento positive-only con baseline, CAS, Ollama y epsilon 0.10.
12. Promoción sólo de candidatos aceptados a 4_procesado.
13. Compartición atómica a 5_compartido tras aprobación independiente.
14. Discusión JSON inmutable con autor, comentario fijado y respuestas.
15. Bridge PyWebView con identificadores opacos y validación de revisiones.
16. Chat contextual con citas de identidad, revisión, hash, título y origen.
17. Modal de reunión con consentimiento, recuperación y estados controlados.
18. Operación --flush, --headless y consola de escritorio.

## Capacidades que requieren instalación o entorno real

1. Instalador macOS y entorno virtual limpio.
2. Arranque de consola fuera del checkout.
3. Accesos directos y permisos de escritura.
4. PyWebView real, foco, teclado, modal y cierre.
5. Micrófono y permisos de captura del sistema.
6. Puente local de Meetily con ejecutable configurado.
7. Grabación, transcripción y nota de reunión en rutas reales.
8. OneDrive/SharePoint montado por cliente oficial.
9. Lectura de 1_volcado/común y escritura controlada de 5_compartido.
10. Ollama instalado, modelo disponible y presupuesto de RAM real.
11. OCR, audio, Docling y MiniRAG con extras instalados.
12. Instalador Windows, exe y comportamiento Windows.
13. Responsive visual en ventanas reales.

## Fuera de alcance actual

- OAuth, Microsoft Graph y configuración automática de OneDrive/SharePoint.
- Filtrado propio de permisos de SharePoint.
- Backend cloud multiusuario para discusiones.
- Cuentas, notificaciones y presencia colaborativa de Fuente.
- Iframe web o backend histórico FastAPI de Meetily.
- Descarga automática de modelos Ollama.
- Paridad completa con Word/Obsidian; Fuente sí incluye edición visual WYSIWYG
  local sobre Markdown mediante Toast UI.
- Despliegue SaaS o servicio remoto de Fuente.

## Evidencia obligatoria

Cada prueba registra ID, fecha, sistema operativo, Python, commit, paquete, Vault o corpus, pasos, resultado esperado, resultado observado, hashes y limitaciones. Nunca registrar tokens, audio sensible ni transcripciones reales en Git.

## Gates

- G0: checkout limpio, commit identificado, suite y release gate verdes.
- G1: artefacto macOS generado e inspeccionado.
- G2: instalación macOS limpia arranca y conserva datos.
- G3: ETL, aprobación, RAG, refinamiento y UI funcionan con corpus sintético.
- G4: Meetily funciona con consentimiento y permisos reales.
- G5: Vault y carpetas montadas respetan rutas autorizadas.
- G6: Windows validado por separado o marcado NOT_RUN.
- G7: informe final separa implementado, probado, publicado y desplegado.

Un gate fallido no se convierte en COMPLETE por pasar una prueba posterior.

## Orden operativo

1. PR-00 baseline y corpus sintético.
2. PR-04 real: copia autorizada de Vault, layout, migración y aprobación.
3. PR-05 real: ETL con archivos reales y motores instalados.
4. PR-06 sintética y real: MiniRAG, Chroma, Ollama y refinamiento.
5. PR-07 sintética y real: editor, aprobación, compartir y discusión.
6. PR-01 sintética y real: artefacto macOS.
7. PR-03 sintética y real: instalación macOS limpia.
8. PR-08 sintética y real: interfaz instalada.
9. PR-09 sintética y real: Meetily, micrófono, audio y transcripción.
10. PR-10 sintética y real: dry-run y migración de General, si se resuelven IDs duplicados.
11. PR-11 sintética y real: carpetas OneDrive/SharePoint montadas.
12. PR-02 sintética y real: Windows, si hay máquina disponible.
13. PR-12 decisión final basada en resultados S/R.

### Addendum de campaña real continuada — 2026-08-25

La aplicación instalada se probó de nuevo sin Chrome sobre el Vault real
`/Users/emiliosevillaortego/Desktop/Nuevo Vault`. El editor Toast UI se validó
en WYSIWYG y Markdown: el cambio de modo ya no produce un falso estado sucio,
una edición real sí activa `Cambios sin guardar`, Guardar persiste y la
restauración posterior dejó la fixture sin `QA_EDIT_TEMP_20260825`.

También se observaron en la aplicación instalada: chat contextual de nota y
de bóveda con recuperación BM25 cuando no hay modelo local, apertura real de
la nota en Obsidian, copia al portapapeles, exportación Markdown real a
`~/Downloads`, previsualización de fusión sin candidatos y formulario de
reunión. La reunión no se declara PASS: al iniciar muestra el error explícito
`Meetily bridge executable is missing`, sin crash.

Evidencias principales: `/tmp/fuente-real-editor-mode3-markdown-fixed.png`,
`/tmp/fuente-real-editor-mode3-wysiwyg-back-fixed.png`,
`/tmp/fuente-real-editor-mode3-save-result.png`,
`/tmp/fuente-real-editor-restore-after-save.png`,
`/tmp/fuente-real-chat-answer.png`, `/tmp/fuente-real-chat-all-answer.png`,
`/tmp/fuente-real-obsidian-open-result.png`,
`/tmp/fuente-real-reader-export-result.png`,
`/tmp/fuente-real-fusion-open.png` y
`/tmp/fuente-real-meeting-start-result.png`.

El paquete final medido en esta campaña fue: DMG `32.079.998` bytes,
SHA-256 `8c980a3cfad34d845dddc09d72d5a6c73ab96d54b216235df4b50d23887baa63`;
ZIP `32.462.138` bytes, SHA-256
`0a5b6b8b4c5ec9d084c93867d7d56fa2d4d7dc7167170678b614a0c1be80ed42`.
Estado: `R REAL: PARTIAL`; no se convierte en completo mientras falten la
dependencia Meetily configurada y los entornos no disponibles.

La repetición sobre la build posterior cerró además las exportaciones de
documentos. El primer PDF real reveló que `window.open()` era bloqueado por
PyWebView; se corrigió la rama para usar `window.print()` nativo en la ventana
actual y recargar la consola tras `afterprint`. La build reinstalada mostró el
diálogo nativo de macOS y produjo el PDF válido
`/Users/emiliosevillaortego/Desktop/v.pdf`, de una página y con SHA-256
`dcf55c5025396dfe05f700c0c72977d241a6302e2fa6055d4c6ebedcab1dfd232`.

La exportación Word real produjo el OOXML válido
`/Users/emiliosevillaortego/Downloads/QA_Ingesta_Vinculada_20260825.docx`,
SHA-256 `cdc430fe3d31046684ce56bda0cd298b7c88ad92c42f0126865b322f8c37a8ee`.
Capturas: `/tmp/fuente-real-pdf-native-dialog.png`,
`/tmp/fuente-real-pdf-saved.png` y
`/tmp/fuente-real-export-word-result-2.png`.

### Evidencia real adicional de controles — 2026-08-25

La consola instalada se ejercitó sin Chrome. Se abrieron Guía Rápida, Ajustes,
Energy, Tema, Nuevo Flujo, Actualizar entradas, Bandeja, Cola, Salud, las
tarjetas de estadísticas y el registro. Los cambios de Energy, la selección de
margen RAM, la purga de memoria, la actualización de una carpeta vinculada,
la ejecución del flujo y el refresco de la cola produjeron efectos visibles y
comprobables en el Vault o en la interfaz.

La prueba real de entrada vinculada dejó el job en `completed/completed`, cinco
notas procesadas y cero pendientes. El Vault de prueba conserva `.obsidian`,
las carpetas canónicas y los artefactos ya medidos. Salud mostró Vault, Ollama
y Tesseract como `ok`; la medición RAM permitió purgar y notificó los objetos
liberados.

La Cuarentena mostró tres elementos `failed_for_review` con
`invalid_model_output`. La interfaz no ofreció Restaurar, conforme a la
protección del backend para salidas inválidas; se corrigió el texto de la Guía
para no prometer restauración en ese estado. La build reinstalada mostró el
texto corregido y mantuvo los registros sin acción de restauración.

### Meetily nativo real — 2026-08-25

Meetily se abrió como aplicación macOS y se probó con el micrófono real del
MacBook Air. La grabación inició con `Recording` y `Listening for speech...`,
se confirmó el aviso de participantes y se detuvo sin error. Meetily creó
`audio.mp4`, `metadata.json` y `transcripts.json`; el registro quedó en estado
`completed` y `transcripts.json` contiene cero segmentos porque la prueba no
incluyó voz. Esta evidencia demuestra que Meetily, el permiso de micrófono y
la escritura local de audio funcionan por separado.

El gate G4 sigue pendiente: la aplicación Fuente no puede iniciar esa misma
sesión porque el puente local aprobado `/opt/meetily-bridge` no está instalado.
No se usa la ventana de Meetily como sustituto del puente ni se declara la
integración como PASS.

La misma prueba se repitió en la reinstalación final con título, autor y
consentimiento cumplimentados. Fuente permaneció abierta y mostró
`Meetily bridge executable is missing`; no creó artefactos de reunión en el
Vault. El estado real sigue siendo `R REAL: PARTIAL` hasta resolver el bridge
aprobado. Evidencia: `/tmp/fuente-real-reinstalled-meeting-missing-bridge.png`,
SHA-256
`096f9f59bc4abc83c1702328365ebf65c1970bac10fa6e6dfe6db25264c94109`.

Al reabrir el formulario no se inició ninguna captura. Al retirar el
consentimiento, `Iniciar grabación` quedó deshabilitado y no se creó sesión ni
artefacto; la interfaz mantuvo visible el error previo del bridge sin cerrar
Fuente. Evidencia adicional:
`/tmp/fuente-real-reinstalled-meeting-consent-rejected.png`.

La misma reinstalación ejecutó `Nuevo Flujo de Trabajo` con el Vault real ya
procesado. La interfaz mostró `Nuevo Flujo de Trabajo completado exitosamente`
y conservó `0` pendientes, `5` procesados, `3` en cuarentena y `5` notas, sin
cierre inesperado. Evidencia: `/tmp/fuente-real-reinstalled-workflow-final.png`.
