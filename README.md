# Funes — Knowledge Base ETL para Obsidian

**Funes** es un sistema ETL (Extracción, Transformación y Carga) y Knowledge Base inteligente diseñado para procesar flujos diarios de archivos multiformato desestructurados y volcarlos automáticamente en un **Vault de Obsidian** como notas atómicas hiperconectadas (`[[WikiLinks]]`).

---

## 🚀 Características Principales

1. **Flujo ETL de 4 Etapas**:
   - `1_entrada/`: Escucha continua de archivos volcados en bruto.
   - `2_sucio/`: Copia de respaldo de archivos originales.
   - `3_limpio/`: Conversión verbatim a Markdown plano (`.md`).
   - `4_salida/`: Notas atómicas estructuradas en el formato estándar con metadatos e interconexión masiva.
2. **Soporte Multiformato**:
   - Documentos: PDF, DOCX, DOC, XLSX, XLS, PPTX, MSG, TXT, MD.
   - Formato Académico/Científico: LaTeX (`.tex`), TeXmacs (`.tm`) preservando expresiones matemáticas `$math$`.
   - Audio: Transcripción automática local de MP3, WAV, M4A con **Faster-Whisper**.
   - Imágenes: OCR local para PNG, JPEG, TIFF.
3. **RAM Governor (IA Adaptativa Local)**:
   - Mantiene una holgura libre del 35% de RAM del sistema para evitar congelamientos o lag.
   - Selecciona automáticamente el modelo LLM óptimo vía Ollama:
     - **RAM <= 8 GB**: `Qwen 1.5 2B` / `Qwen 2.5 1.5B`
     - **RAM 8 - 16 GB**: `Qwen 2.5 3B` / `Qwen 2.5 7B`
     - **RAM 16 - 32 GB**: `Qwen 2.5 14B` / `Command-R 35B`
     - **RAM > 32 GB**: `Qwen 2.5 32B` / `Command-R`
4. **Bucle de Grafo Estilo Karpathy (`KarpathyGraphLoop`)**:
   - Hilo autónomo en segundo plano que re-evalúa notas, inserta enlaces `[[WikiLinks]]` cruzados y actualiza el mapa global de conocimiento (`_Indice_MOC.md`).
5. **Base Vectorial ChromaDB embebida**:
   - Indexación semántica y chunking por significado (estilo RAGAnything).

---

## 📦 Instalación y Uso Rápido

### Opción 1: Ejecutar desde código fuente (Desarrolladores)
```bash
# 1. Clonar repositorio
cd funes

# 2. Ejecutar tests de verificación
python3 -m unittest discover -s tests

# 3. Iniciar Funes vinculándolo a tu Vault de Obsidian
python3 funes/main.py --vault "/Ruta/A/Tu/ObsidianVault"
```

### Opción 2: Compilar Ejecutable Autónomo (Windows / macOS)
```bash
python3 build_installer.py
```
El ejecutable binario se generará en la carpeta `dist/FunesKnowledgeBase`.

---

## 📄 Plantilla de Nota Atómica Generada (`4_salida`)

Las notas en `4_salida/` siguen la estructura unificada requerida:

```markdown
---
title: "Título de la Nota"
date: "AAAA-MM-DD"
author: "Autor"
tags: [tema1, tema2]
problem: "Descripción del problema"
---

# Título de la Nota

## Resumen Ejecutivo
- **¿Qué?**: Explicación concreta
- **¿Cuándo?**: Contexto temporal
- **¿Quién?**: Entidades o personas
- **¿Cómo?**: Proceso aplicado

## Problema
...
## Contexto
...
## Objetivo
...
## Método
...
## Desarrollo
...
## Resultado
...
```

---

## 🛠️ Licencia e Información
Desarrollado bajo licencia MIT para la gestión inteligente y soberana de conocimiento local con privacidad total.