# Auditoría sintética y guion de pruebas reales

Fecha: 2026-08-24
Alcance: PR-12 S documental. No se ejecutó ninguna suite completa ni se usó el Vault real. Este informe quedó registrado en el commit final de documentación.

## Resultado

La auditoría confirma que las fases tienen estado S/R documentado, que `NOT_RUN` no se convierte en `PASS` por inferencia y que el estado global correcto de la campaña es `PARTIAL`. PR-12 queda en `S PASS / R NOT_RUN / PARTIAL`: el informe está preparado, pero la decisión final real queda pendiente de ejecutar el guion siguiente.

| Fase | S | R | Global | Comando o evidencia principal | Límite actual |
|---|---|---|---|---|---|
| PR-00 | PASS | PASS | COMPLETE | `task-PR-00-S-rerun-report.md`; `task-PR-00-R-report.md`; suite y release gate en clon limpio | No acredita instalación, UI, hardware, Vault real ni Windows |
| PR-04 | PASS | PARTIAL | PARTIAL | `task-PR-04-S-report.md`; `task-PR-04-R-report.md`; `task-PR-04-R-rerun-date-fix-report.md`; layout y dry-run | `apply`, inventario posterior y rollback quedaron `NOT_RUN` |
| PR-05 | PASS | PASS | COMPLETE | `task-PR-05-S-report.md`; `task-PR-05-R-report.md`; probes ETL | Sólo el corpus/Vault autorizado descrito en el informe |
| PR-06 | PASS | NOT_RUN | PARTIAL | `task-PR-06-S-report.md`; `36 passed` focales | Ollama, almacenamiento real y notas reales pendientes |
| PR-07 | PASS | NOT_RUN | PARTIAL | `task-PR-07-S-report.md`; `28 passed` focales | PyWebView, escritura real, compartir y discusión visual pendientes |
| PR-01 | PASS | NOT_RUN | PARTIAL | `task-PR-01-S-report.md`; ZIP, hashes, exclusiones y smoke CLI | Falta validación real fuera del checkout |
| PR-03 | PASS | NOT_RUN | PARTIAL | `task-PR-03-S-report.md`; probe desde ZIP, instalación sintética y `23 passed` | Falta instalación limpia interactiva |
| PR-08 | PASS | NOT_RUN | PARTIAL | `task-PR-08-S-report.md`; `269 passed`, `4/4` JS | Falta ventana instalada, teclado, foco, lector de pantalla y 375 px reales |
| PR-09 | PASS | NOT_RUN | PARTIAL | `task-PR-09-S-report.md`; `106 passed` | Falta Meetily, micrófono, audio, permisos y transcripción real |
| PR-10 | PASS | NOT_RUN | PARTIAL | `task-PR-10-S-report.md`; `134 passed` | Falta copia autorizada de General; no forzar IDs duplicados |
| PR-11 | PASS | NOT_RUN | PARTIAL | `task-PR-11-S-report.md`; `70 + 34 passed` | Falta ruta montada real y autenticación del proveedor |
| PR-02 | PASS | NOT_RUN | PARTIAL | `task-PR-02-S-report.md`; `132 passed`; host macOS medido | Falta Windows real, `.exe` y smoke Windows |
| PR-12 | PASS | NOT_RUN | PARTIAL | Este informe; auditoría documental y `git diff --check` | La decisión final depende de R reales |

Los informes con estados anteriores se conservan como historial. La tabla usa el estado activo del plan/spec y sólo acepta `PASS` cuando existe evidencia explícita dentro del alcance indicado.

## Trazabilidad y límites

- Commits de las fases sintéticas: `c45ee95`, `12899f9`, `80e4c7b`, `1347cc5`, `35ad154`, `064077a`, `eb3c095`, `c0ae001`, `60a018b` y `8565dd0`; auditoría final: `10ec0f3`.
- Los informes de PR-08, PR-09, PR-10, PR-11 y PR-02 declaran expresamente `S PASS`, `R NOT_RUN` y no commit propio; la auditoría no los eleva.
- `dist/` no es despliegue: queda fuera de Git y no cambia el estado de ninguna fase.
- Las carpetas canónicas son `1_volcado`, `2_copiado`, `3_capturado`, `4_procesado` y `5_compartido`. `3_capturado` es la fuente canónica; `5_compartido` exige aprobación.
- No se deben guardar audio, transcripciones, tokens, Vaults ni datos personales reales en Git.

## Guion de pruebas reales

Ejecutar cada bloque con una copia autorizada, registrar fecha, sistema, Python, commit, rutas, resultado esperado/observado y hashes. Si falta permiso, hardware o plataforma, registrar `NOT_RUN` o `BLOCKED`; no registrar `PASS`.

1. **PR-00 — baseline.** Crear un clon temporal limpio en rama `dev`, medir `git status`, `HEAD`, Python y plataforma, y ejecutar sólo el gate definido. Guardar la salida fuera de Git. Esperado: árbol limpio y gate `READY`.
2. **PR-04 — Vault y migración.** Trabajar sólo sobre una copia autorizada del Vault. Verificar raíces canónicas, ejecutar `migrate_vault.py --dry-run`, revisar frontmatter y duplicados, y detenerse ante cualquier hallazgo. Sólo con aprobación humana explícita ejecutar `apply`; comprobar hashes, manifiesto y rollback en la copia. Nunca tocar el original.
3. **PR-05 — ETL real.** Usar archivos reales autorizados en `1_volcado`; ejecutar el probe ETL dos veces, comparar salidas y registrar motores, errores, hashes y memoria. Esperado: originales intactos y estados de aprobación claros antes de `4_procesado`.
4. **PR-06 — RAG y refinamiento.** Con Ollama y el modelo autorizado disponibles, indexar una copia aprobada de `3_capturado`, consultar una pregunta conocida, comprobar procedencia y probar una edición/refinamiento con control CAS. No publicar en `5_compartido` sin aprobación.
5. **PR-07 — editor y compartir.** En instalación limpia, editar una nota procesada, comprobar que cambia su hash y que compartir queda bloqueado hasta nueva aprobación; aprobar, compartir y abrir una discusión. Verificar que sólo la salida aprobada llega a `5_compartido`.
6. **PR-01 — paquete macOS.** Copiar el ZIP fuera del checkout, verificar SHA-256 y `unzip -t`, extraerlo, arrancar el binario y registrar ayuda, error controlado y cierre. No llamar `dist/` desplegado.
7. **PR-03 — instalación macOS.** Ejecutar `instalar_fuente.command` desde el paquete limpio en una carpeta temporal. Completar selector de Vault y accesos; comprobar recibo, permisos y las cinco carpetas. No descargar modelo ni extras sin autorización explícita.
8. **PR-08 — UI instalada.** Abrir la aplicación instalada y comprobar consola, lector, editor, modales, foco, teclado, lector de pantalla y viewport de 375 px. Registrar capturas sólo si no contienen datos reales.
9. **PR-09 — reunión local.** Con consentimiento y permiso de micrófono, iniciar Meetily, grabar 30–60 s de audio de prueba, detener, importar y verificar recuperación/idempotencia. Guardar audio/transcripción sólo fuera del repositorio y eliminar la copia temporal al cerrar.
10. **PR-10 — General.** Sobre copia autorizada, inventariar y hacer `dry-run`; resolver primero `duplicate_note_id` y frontmatter inválido. Sólo con identidad, revisión y aprobación registradas ejecutar `apply`, comprobar hashes y probar rollback sin editar el original.
11. **PR-11 — carpeta montada.** Con una ruta OneDrive/SharePoint ya montada y permisos existentes, probar descubrimiento y copia controlada. Fuente no configura OAuth, Graph ni permisos. Verificar entrada sólo en `1_volcado` y salida aprobada sólo en `5_compartido`.
12. **PR-02 — Windows.** En una máquina Windows real, construir el paquete, comprobar `.exe`, recursos, instalación limpia y smoke de arranque/cierre. Registrar versión de Windows, Python, arquitectura y hashes. En macOS no se puede convertir esta fase en `PASS`.
13. **PR-12 — cierre.** Releer todos los informes, confirmar que cada S/R tiene evidencia, clasificar `PASS`, `FAIL`, `BLOCKED` o `NOT_RUN`, actualizar el ledger y decidir: `APTO PARA PRUEBA DIARIA`, `APTO CON LIMITACIONES` o `NO APTO`.

### Criterio de seguridad

Toda escritura se hace sobre copias temporales o Vaults autorizados. El flujo debe conservar `1_volcado → 2_copiado → 3_capturado → 4_procesado → 5_compartido`; compartir exige aprobación independiente. Ante duda, detenerse y dejar `NOT_RUN`.
