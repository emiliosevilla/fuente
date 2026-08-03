# 🧠 Funes: Infografía Explicativa del Sistema

> **"El tejedor local de conocimiento que transforma el caos de archivos en un Segundo Cerebro conectado en Obsidian."**

---

## 📐 1. Arquitectura General y Flujo ETL en 4 Etapas

Funes opera mediante un pipeline de extracción, transformación y carga (ETL) continuo e incremental de 4 fases que procesa archivos desestructurados en bruto y los convierte en notas atómicas interconectadas en **Obsidian**.

```mermaid
flowchart TD
    subgraph INGESTA ["1. Ingesta Continua"]
        E["📁 1_entrada/"] -->|Archivos desestructurados| W["👀 Watcher / Monitor local"]
    end

    subgraph PROCESAMIENTO ["2. Transformación y Limpieza"]
        W -->|Backup Verbatim| S["📁 2_sucio/ (Auditoría)"]
        W -->|Extracción de Texto / OCR / Whisper| L["📁 3_limpio/ (.md Verbatim)"]
    end

    subgraph ESTRUCTURACION ["3. Generación Atómica"]
        L -->|LLM + Prompts Estructurados| A["📁 4_salida/ (Notas Atómicas)"]
        A -->|Inserción de WikiLinks| MOC["📄 _Indice_MOC.md"]
    end

    subgraph GOBERNANZA ["4. Persistencia y Control"]
        A -->|Vectores de contexto| C["🗄️ .funes/ChromaDB"]
        W -->|Errores / Incompatibles| Q["⚠️ .funes/quarantine/"]
    end

    classDef stage fill:#2d3748,stroke:#4a5568,color:#fff;
    classDef output fill:#1a202c,stroke:#3182ce,color:#63b3ed;
    classDef quarantine fill:#742a2a,stroke:#e53e3e,color:#feb2b2;
    
    class E,S,L stage;
    class A,MOC output;
    class Q quarantine;
```

---

## ⚙️ 2. El Motor de Extracción Multiformato

Funes procesa automáticamente cualquier tipo de documento convirtiéndolo a texto limpio sin alterar los archivos originales.

| Categoría | Formatos Soportados | Tecnología de Extracción | Salida Resultante |
| :--- | :--- | :--- | :--- |
| **Documentos y Tablas** | `PDF`, `DOCX`, `XLSX`, `PPTX`, `CSV`, `HTML`, `MSG`, `TXT` | Parsers nativos + OpenPyXL + Docx | Markdown formateado con tablas limpios |
| **Académico / Científico** | `LaTeX (.tex)`, `TeXmacs (.tm)` | Extractor de ecuaciones | Preserva notación matemática `$math$` |
| **Audio y Notas de Voz** | `MP3`, `WAV`, `M4A`, `OGG`, `FLAC` | **Faster-Whisper** (Local) | Transcripción literal con marcas de tiempo |
| **Imágenes y Escaneos** | `PNG`, `JPG`, `TIFF`, `BMP` | **Tesseract OCR** (Local) | Texto reconocido sin depender de internet |

---

## 🎛️ 3. `RAM Governor`: IA Adaptativa según Hardware

Para evitar congelamientos del sistema, el **RAM Governor** monitoriza continuamente la memoria física y mantiene un margen de holgura libre del **35%**, seleccionando en tiempo real el modelo de **Ollama** óptimo.

```mermaid
flowchart TD
    RAM["💻 Medición de RAM Libre del Sistema"] --> C1{"¿Cuánta RAM hay disponible?"}
    
    C1 -->|"≤ 8 GB"| M1["⚡ Qwen 1.5B / 2.5 1.5B"]
    C1 -->|"8 – 16 GB"| M2["🚀 Qwen 2.5 3B / 7B"]
    C1 -->|"16 – 32 GB"| M3["🧠 Qwen 2.5 14B / Command-R 35B"]
    C1 -->|"> 32 GB"| M4["🔥 Qwen 2.5 32B / Command-R"]

    M1 --> OUT["⚙️ Ingesta Activa (Holgura del 35% libre)"]
    M2 --> OUT
    M3 --> OUT
    M4 --> OUT
```

---

## 🔄 4. Bucle de Grafo Optimizado (`OptimizadoGraphLoop`)

En segundo plano, un hilo autónomo re-evalúa de forma continua la red de notas para descubrir relaciones implícitas y mantener el conocimiento vivo.

```mermaid
flowchart LR
    N1["📄 Nota Atómica Nueva"] -->|Evaluación semántica| KG["🌀 Bucle Optimizado"]
    KG -->|Identifica conceptos clave| WL["🔗 Inserción de WikiLinks"]
    KG -->|Actualiza jerarquía| MOC["🗺️ _Indice_MOC.md (Map of Content)"]
    WL --> N2["📄 Notas Antiguas Relacionadas"]
```

> [!TIP]
> **Map of Content (MOC):** `_Indice_MOC.md` es el mapa temático auto-generado que clasifica automáticamente todas tus notas por temas, áreas de interés y cronología.

---

## 🛡️ 5. Tolerancia a Fallos y Alta Disponibilidad

> [!IMPORTANT]
> **Funes está diseñado para resistir las peculiaridades de los sistemas de archivos reales:**
> - **Filtro de archivos temporales**: Ignora automáticamente archivos borrador de Microsoft Office (`~$*`), descargas en curso (`.crdownload`, `.part`) y archivos bloqueados (`.tmp`, `.lock`).
> - **Aislamiento en Cuarentena**: Archivos dañados o no procesables se trasladan a `.funes/quarantine/` sin interrumpir la ingesta del resto del volumen.
> - **Resiliencia de Red**: Retrasos adaptativos para evitar errores por micro-cortes en carpetas compartidas por red (`SMB / NFS`).

---

## 📄 6. Anatomía de una Nota Atómica Generada (`4_salida/`)

Cada documento procesado se convierte en una nota limpia en Markdown lista para navegar en **Obsidian**:

```markdown
---
título: "Análisis de Ingesta Inteligente"
fecha: "2026-07-30"
autor: "Funes Core"
claves: [etl, obsidian, wikilinks, inteligencia-artificial]
fuentes: [3_limpio/documento_original.md]
---

# Análisis de Ingesta Inteligente

## Resumen Ejecutivo
- **¿Qué?**: Proceso de conversión estructurada de archivos.
- **¿Cuándo?**: Ingesta en tiempo real.
- **¿Quién?**: Funes ETL Engine.
- **¿Cómo?**: Extracción + LLM local + Grafo semántico.

## Contenido Principal
...

## Referencias Cruzadas
### Notas Relacionadas
- [[Nota_Sobre_RAM_Governor]]
- [[Documento_Graph_Optimizado]]
- [[Indice_MOC_General]]
```

---

## 🌟 Resumen de Puntos Fuertes

| Característica | Beneficio |
| :--- | :--- |
| **🔒 100% Local y Privado** | Sin APIs externas ni costes por token; tus datos no salen de tu equipo. |
| **🌐 Hiperconectado** | Enlaces automáticos `[[WikiLinks]]` para explorar tu información visualmente en el grafo de Obsidian. |
| **⚡ 1-Clic Launch** | Lanzadores automáticos para macOS (`instalar_funes.command`) y Windows (`instalar_funes.bat`). |
| **🎨 Interfaz Consola Vintage** | Consola de control con estética gráfica *Watergate Press* para monitorizar el proceso con estilo. |
