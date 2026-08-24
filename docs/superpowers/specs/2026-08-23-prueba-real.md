# SDD: prueba_real de Fuente

## Objetivo

Validar la versión publicada de Fuente en dos niveles: primero desde el repositorio y después como instalación real de usuario. El resultado debe separar qué funciona, qué funciona sólo bajo condiciones concretas y qué no está implementado.

Este SDD no añade funcionalidades de producto. Organiza construcción de artefactos, instalación, pruebas de aceptación y registro de resultados.

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

Estado activo inicial de la campaña: todas las fases estaban `NOT_RUN`. Estado actual: PR-00 y PR-04 tienen `S PASS`, `R PASS` y están `COMPLETE`; PR-05 y las fases posteriores siguen `NOT_RUN`. El orden obligatorio es: PR-00, PR-04, PR-05, PR-06, PR-07, PR-01, PR-03, PR-08, PR-09, PR-10, PR-11, PR-02, PR-12. Cada fase ejecuta primero `S` sintética y sólo si pasa ejecuta `R` real.

`PR-10` repite su prueba sintética y no hereda automáticamente el bloqueo histórico por IDs duplicados. En el estado actual PR-00 y PR-04 están `COMPLETE` y PR-05+ están `NOT_RUN`.

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
- WYSIWYG completo.
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
