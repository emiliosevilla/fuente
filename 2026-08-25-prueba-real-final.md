# Informe final de prueba real — Fuente macOS

Fecha: 2026-08-25

Aplicación: `/Applications/Fuente.app`

Vault real: `/Users/emiliosevillaortego/Desktop/Nuevo Vault`

Motor visual: WebKit nativo mediante PyWebView. Chrome no se usó ni forma parte del producto.

## Veredicto

`PASS` para Fuente en macOS y para el flujo local comprobado. La aplicación
instalada arranca en frío, conecta el Vault real, ejecuta el flujo ETL, permite
revisar y consultar notas, muestra el mapa en una vista independiente, integra
la biblioteca local de Meetily y produce paquetes macOS firmados de forma
coherente.

No se declara probado lo que no estuvo disponible: Windows y carpetas
OneDrive/SharePoint montadas. Esos límites no rebajan el resultado macOS, pero
siguen siendo límites de plataforma reales.

## Bundle final instalado

- DMG: `32.129.588` bytes. SHA-256:
  `1d1ac3d9276330840c76cbb448fbf9723af223798f6ab4aadf0c1be7aa71ac1e`.
- ZIP: `32.390.918` bytes. SHA-256:
  `1d46ab53517be54e56897c7af15b0c1e3bdf8f8b7fddcb948adf03eb8b4119d9`.
- HTML fuente, ZIP, DMG y app instalada: SHA-256 común
  `064900c3de8738f09a16fd0d70c8d41049d48d3cf2f65cb7762c5cac0cef7eac`.
- `codesign --verify --deep --strict` pasó sobre la app extraída del ZIP, la
  app montada desde el DMG y `/Applications/Fuente.app`.
- El runtime distribuido no contiene `fuente/browser_server.py`; la opción
  `--browser` fue retirada. La interfaz de usuario es la aplicación nativa.

## Pruebas reales ejecutadas

### Arranque y consola

- Arranque en frío del bundle final por medio de macOS `open`.
- Conexión visible al Vault real en menos de 8 segundos.
- Estado real mostrado: 4 archivos pendientes, 12 procesados, 8 en cuarentena
  y 12 notas preparadas.
- Guía rápida comprobada con sus cinco pasos y ventana `+ Info`.
- Ajustes comprobados en las pestañas `Carpetas` e `IA`.
- Estado del sistema comprobado con Vault, Ollama, Tesseract y FFmpeg medidos.
- Trabajos e historial comprobados con términos de usuario, fechas locales y
  motivos traducidos; no se muestran estados internos como `saved_clean`.

### Notas, búsqueda, mapa y revisión

- Bandeja `Revisar notas`: carga real de notas pendientes y apertura de sus
  campos de revisión.
- Espacio `Notas`: biblioteca jerárquica compacta, lectura del MOC, contexto y
  acciones de edición, consulta, copia, exportación, Obsidian, unión y reunión.
- Búsqueda de frase completa con espacios:
  `QA Prueba Real Raiz 20260824`; la frase se conservó completa y dejó un único
  resultado correspondiente.
- Mapa independiente: 25 notas, 6 enlaces y 18 orígenes; zoom y centrado
  comprobados desde sus controles.
- La auditoría previa de los 15 modales se conserva como evidencia diferencial;
  este ciclo volvió a probar las superficies modificadas y sus estados reales.

### Ingesta, ETL, audio y publicación

- Ingesta real de Markdown, Word, PDF, JSON y audio.
- Ciclo de copia, extracción, captura canónica, revisión, procesamiento,
  exportación y compartición.
- Reintroducción del audio
  `QA_Reintroducido_Audio_Final2_20260825.mp3`: creó una única captura
  `3_capturado/QA_Reintroducido_Audio_Final2_20260825.md`, quedó esperando
  revisión y no añadió una cuarentena falsa.
- Audio real de 180,62 segundos transcrito localmente con Faster-Whisper:
  464 palabras en 6,2 segundos.
- Exportación Markdown, PDF y DOCX; copia, apertura en Obsidian, compartir y
  conversación sobre la copia compartida comprobados.

### Meetily y MiniRAG

- Meetily se abre como aplicación local y Fuente muestra dentro de `Reunión`
  su biblioteca local de grabaciones. La prueba final mostró tres reuniones
  detectadas y acciones de importación disponibles.
- La importación mantiene audio, metadatos y transcripción enlazados y continúa
  por el ETL normal de Fuente.
- MiniRAG oficial fijado se ejecutó con Ollama local y el modelo explícito
  `qwen3.5:0.8b`: 3 nodos, 3 enlaces y procedencia exacta en 28,65 segundos.
- Con poca memoria, Fuente degradó correctamente a BM25 sin fingir que MiniRAG
  estaba activo.

## Fallos encontrados y corregidos en el ciclo final

- Falso error de conexión en el primer arranque: el estado inicial dispone de
  un plazo propio para inventariar el Vault.
- `Revisar notas` abría la bandeja pero no iniciaba su carga: ahora carga en
  cada apertura.
- `Trabajos` exponía UUID completos, estados internos y errores en inglés: la
  vista presenta referencias cortas, pasos y motivos claros sin modificar el
  protocolo persistente.
- El modo web/Chrome seguía disponible por CLI y servidor HTTP: eliminado por
  completo junto con sus pruebas y documentación.

## Suite y evidencia automática

La ejecución final estable produjo `1369 passed, 1 skipped, 227 warnings` en
74,65 segundos. El resultado y el hash del árbol quedan registrados también en
`docs/evidence/current-sdd.json`.

## Seguridad residual

| Hallazgo | Severity | Status |
| --- | --- | --- |
| Ningún hallazgo bloqueante abierto tras la suite de seguridad | P1 | resolved |

## Capturas finales

- `/tmp/fuente-release-final-main.png`
- `/tmp/fuente-final-guide-info-7.png`
- `/tmp/fuente-release-approval-loaded.png`
- `/tmp/fuente-release-approval-selected.png`
- `/tmp/fuente-release-notes-workspace.png`
- `/tmp/fuente-release-search-phrase.png`
- `/tmp/fuente-release-map-controls.png`
- `/tmp/fuente-release-meetily-2.png`
- `/tmp/fuente-release-settings.png`
- `/tmp/fuente-release-settings-ai-2.png`
- `/tmp/fuente-release-health.png`
- `/tmp/fuente-release-final-job-history.png`

## Límites comprobados con honestidad

- Windows no se ejecutó en esta máquina.
- No se dispuso de una carpeta real OneDrive/SharePoint montada para una prueba
  de proveedor.
- Los motores opcionales no instalados no se declaran probados. MarkItDown,
  MiniRAG, Ollama, Tesseract, FFmpeg y Faster-Whisper sí fueron detectados o
  ejercitados según se detalla arriba.

Conclusión: Fuente queda operativa y verificada como aplicación nativa macOS.
