# Informe de prueba real — Fuente macOS

Fecha: 2026-08-25  
Aplicación: `/Applications/Fuente.app`  
Vault: `/Users/emiliosevillaortego/Desktop/Nuevo Vault`  
Navegador: no usado.

## Veredicto

`PASS` para el flujo local macOS probado. `R REAL: PARTIAL` como producto
completo: Meetily no aporta el bridge local aprobado, Windows y carpetas
montadas no están probados, y los motores no instalados quedan fuera.

## Instalación

- La app instalada arranca y renderiza la consola.
- El spinner/barra de arranque es visible.
- `codesign --verify --deep --strict /Applications/Fuente.app`: pasa.
- El paquete contiene `Instalador_Fuente.command`; no contiene el lanzador
  antiguo `Fuente.command`.
- DMG: `32.085.275` bytes, SHA-256
  `29d529831620932b68dbffb269bc720d8da9561cdeb5ca8d6b822d6a5c6aa33b`.
- ZIP: `32.464.912` bytes, SHA-256
  `d6602034e07fc654714116bc0799ea767e21598a5e2fd605fce5752c55c5b33e`.

## Flujos reales comprobados

- Detección de Obsidian y selección nativa de Vault.
- Persistencia de ruta, carpetas vinculadas, temas, Energy, guía, estadísticas,
  cola, salud y registro.
- Ingesta real de Markdown, Word, PDF, JSON y audio Meetily.
- Aprobación humana, procesamiento, exportación Markdown/PDF/DOCX, lector,
  copia, apertura en Obsidian, compartir y discusión.
- Editor Toast UI en Markdown, WYSIWYG, vista dividida, Preview y cancelación.
- Chat de nota y de Vault con recuperación local cuando no hay Ollama.
- Handoff real a Meetily instalado. La aplicación oficial abre; el bridge
  embebido no se declara disponible.
- Audio Tiny local con modelo Faster-Whisper ya presente: captura y salida
  procesada comprobadas.

## Prueba crítica repetida

Se reintrodujo en `1_volcado` el mismo audio que había provocado el fallo de
reanudar trabajos terminales, con nombre nuevo:

`QA_Reintroducido_Audio_Final2_20260825.mp3`

SHA-256 de origen:
`1da7c0e79751df1714b92610a89a687a881dd8ebda88ebaaec5fa1d443f8ca37`.

Se pulsó la tarjeta visible `PASO 2 — Transcripción` en la aplicación
instalada. Resultado medido en SQLite:

```text
job_id:       043166d2-9a0d-4179-bf38-50ccc51b44ca
stage:        saved_clean
status:       pending
error_code:   awaiting_clean_approval
attempt_count: 1
```

Comprobaciones:

- El archivo original salió de `1_volcado`.
- Se creó `3_capturado/QA_Reintroducido_Audio_Final2_20260825.md`.
- SHA-256 de la captura:
  `2eff32839f3ef071e5f01b1f405880a682c5eb8dd3988a6520dd8c0f106374b7`.
- No se creó ninguna entrada de cuarentena para `Final2`.
- La aprobación queda pendiente, como exige el flujo de seguridad.

La corrección evita que la consola llame a `resume()` cuando `submit()` ya
devuelve un trabajo terminal. El watcher conserva la misma protección para
eventos repetidos.

## Incidencias corregidas durante la campaña

- Arranque sin feedback: añadido spinner/barra.
- Terminal persistente: el lanzador usa `open` y termina el proceso de shell.
- Diálogo de Vault incorrecto: selección nativa de rutas.
- Ruta no persistida: guardado y relanzamiento corregidos.
- Estado vacío en aprobación: no se envía un estado inválido.
- Audio Tiny bloqueado por presupuesto genérico: presupuesto efectivo por modo.
- Reanudación de jobs terminales: guardia en watcher y consola.
- Editor real: Toast UI conserva Markdown y ofrece WYSIWYG.

## Límites que siguen abiertos

- Meetily funciona como aplicación independiente, pero el bridge local aprobado
  no está distribuido.
- No hay validación real en Windows.
- No se validaron OneDrive/SharePoint montados.
- No se descargan modelos pesados durante esta campaña; se mantienen como
  capacidad opcional bajo demanda.

## Evidencia visual

- `/tmp/fuente-final-fix-startup.png`
- `/tmp/fuente-step2-final2-quartz-logical.png`
- `/tmp/fuente-editor-wysiwyg-final.png`
- `/tmp/fuente-real-meetily-handoff-start.png`
- `/tmp/fuente-audio-complete-real.png`
- `/tmp/fuente-approval-guard-after-step2.png`

Conclusión: la ruta local macOS probada queda operativa. El resultado global no
se eleva a completo mientras sigan pendientes el bridge Meetily y los entornos
no disponibles.
