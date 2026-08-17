# Fuente — Registro canónico, terminología y sistema visual

**Estado:** dirección de producto aprobada; no autoriza todavía cambios de
código, rutas, paquetes, repositorio ni GitHub.

**Prevalencia:** esta especificación prevalece, para los trabajos futuros,
sobre la terminología y el modelo de autoridad de
`2026-08-13-fuente-editorial-library-design.md` y sus planes derivados. La
historia técnica anterior se conserva como referencia de migración.

## 1. Decisiones de producto

1. Los documentos Markdown de `3_limpio` son el único registro canónico del
   conocimiento procesado. La base SQLite, los índices RAG, el grafo, los MOC
   y las notas de `4_salida` son proyecciones reconstruibles.
2. Cada revisión de un documento de `3_limpio` debe ser aprobada expresamente
   por una persona antes de que el flujo cree o actualice contenido derivado.
   Mientras no haya aprobación, el documento sigue siendo editable pero no es
   elegible para el paso siguiente.
3. Cada documento Markdown de `4_salida` requiere una segunda aprobación
   humana, independiente de la canónica, antes de considerarse publicado,
   exportable o disponible como resultado editorial. Esta aprobación no puede
   crear ni sustituir la aprobación de sus orígenes en `3_limpio`.
4. El producto, paquete, configuración, documentación, interfaz y repositorio
   pasarán de **Fuente** a **Fuente** mediante una migración planificada. No se
   debe hacer un cambio parcial de nombre.
5. En el dominio editorial, un **origen** es la referencia verificable al
   documento aprobado de `3_limpio` que sostiene una afirmación. Un **sumario**
   es una nota derivada preparada a partir de uno o varios de esos documentos.
6. La consola adoptará el lenguaje visual de la paleta Nord: Polar Night para
   estructura, Snow Storm para lectura, Frost para acciones y Aurora para
   estados semánticos. La aplicación no se presentará como producto Nord.
7. `qwen3.5:0.8b` será el candidato predeterminado del perfil Auto
   ultra-ligero, destinado a equipos con menos de 8 GB de RAM, cuando supere
   el benchmark local definido en este documento. Usará una ventana de contexto
   de 4.096 tokens y concurrencia uno. `Eco estricto` conserva su significado:
   BM25 sin LLM. No se descarga ningún modelo automáticamente.

## 2. Autoridad, aprobación y trazabilidad

El flujo canónico queda así:

```text
1_entrada → 2_sucio → 3_limpio (edición humana) → aprobación canónica
         → generación de sumario candidato → 4_salida → aprobación editorial
```

`3_limpio` contiene el texto preparado para IA y para edición humana. Cada
documento tiene identidad estable, revisión y hash de contenido. La aprobación
debe registrar, como mínimo, `note_id`, ruta relativa, revisión, hash, persona
revisora y fecha. La validez se rompe si cambia el cuerpo o el frontmatter que
afecta al significado. No se permite aprobar automáticamente ni deducir una
aprobación por estar el archivo en la carpeta.

Un sumario debe incluir referencias `origins` a sus documentos de `3_limpio` y
a la revisión aprobada concreta. La interfaz puede mostrar el sumario para
leer, pero cualquier afirmación recuperada, exportada o explicada debe poder
llevar al origen correspondiente. El borrado o la reconstrucción de
`4_salida` no puede perder el registro canónico.

Los índices pueden incluir sumarios para mejorar la navegación, pero no pueden
convertirse en autoridad: al responder o citar, deben conservar el vínculo con
los orígenes aprobados. Si el origen se edita, sus sumarios quedan marcados
como desactualizados y no se actualizan sin una nueva aprobación de esa
revisión. Un sumario sin su propia aprobación editorial permanece fuera de las
salidas publicables aunque sus orígenes sigan siendo válidos.

## 3. Vocabulario canónico

| Concepto | Nombre nuevo y uso | Nombre anterior a retirar |
|---|---|---|
| Producto | `Fuente` | `Fuente` |
| Documento que sustenta una afirmación | `origen` | `source`, `fuente`, `sources` cuando significan cita |
| Referencias de una nota | `origins` | `sources` |
| Tipo de nota derivada de un documento limpio | `summary` / `sumario` | `source` / `fuente` |
| Clasificación del documento de origen | `origin_kind` | `source_kind` |
| Colección de notas derivadas | `4_salida/Sumarios/` | `4_salida/Fuentes/` |
| Carpeta técnica externa de importación | `entrada`, `proveedor` o `carpeta montada` | `fuente` / `source` |
| Directorio interno de aplicación | `.fuente` | `.fuente` |

La migración puede leer los nombres antiguos durante una ventana temporal y
declarada. El código nuevo, los contratos nuevos y los documentos nuevos no
deben crear valores ni rutas antiguas.

La clasificación recomendada para el frontmatter v3 es:

```yaml
schema_version: 3
note_id: 4ca13d5c-4d78-4f37-8c3c-d1dc530a4dc9
note_type: summary
origin_kind: meeting
origins:
  - note_id: 89a2f4fb-1d7b-4aa1-9793-119970502a00
    revision: 4
    content_hash: sha256:...
    path: Tema/3_limpio/reunion-2026-08-14.md
status: pending_review
```

`origin_kind` describe el tipo del documento del que nace el sumario. Las
notas `concept`, `topic`, `question` y `result` también usarán `origins` cuando
formulen afirmaciones sobre documentos, pero no llevarán `origin_kind` salvo
que sean sumarios. La implementación deberá confirmar esta distinción con una
migración de datos antes de eliminar los campos v2.

Las notas editoriales normales de `4_salida` requieren una segunda aprobación
humana. Quedan fuera de esa bandeja las proyecciones MOC generadas por el
sistema (`_Indice_MOC.md` y `_Cuestion_*.md`): reciben aprobación automática y
su contenido sólo puede incluir notas normales de `4_salida` que ya estén
aprobadas.

## 4. Estructura objetivo del Vault

La estructura por tema queda definida de forma visible y estable:

```text
1_entrada/
2_sucio/
3_limpio/                       # único registro canónico; revisión humana
4_salida/
├── Sumarios/
│   ├── Llamadas/
│   ├── Reuniones/
│   ├── Correos/
│   ├── Documentos_Trabajo/
│   ├── Documentos_Oficiales/
│   └── Sin_clasificar/
├── Conceptos/
├── Temas/
├── Cuestiones/
├── Resultados/
├── _Indice_MOC.md
└── _Vistas/
```

`4_salida` no es una segunda fuente de verdad. Es una biblioteca editorial
derivada: sus notas pueden ser revisadas y aprobadas para publicación, pero su
procedencia siempre se conserva en `3_limpio` mediante `origins`.

## 5. Cambio completo de Fuente a Fuente

La conversión comprende, como una única entrega coordinada: nombre de
repositorio y remoto, directorio Python `fuente/`, distribución y comandos,
variables y textos de interfaz, archivos de configuración, `.fuente`, recibos
de instalador, rutas de Vault, pruebas, documentación, ejemplos y nombres de
artefactos. También comprende las rutas `Fuente_Vault` que el instalador o los
ejemplos creen.

Antes de ejecutar la conversión se hará inventario por categoría y se publicará
un manifiesto de migración. La migración deberá ser reanudable, detectar
colisiones, conservar copias de seguridad y poder volver atrás mientras no se
hayan producido ediciones humanas posteriores. Renombrar el repositorio remoto
o cerrar/alterar PRs son operaciones humanas separadas; esta especificación no
las ejecuta.

## 6. Sistema visual basado en Nord

El directorio local `nord/` se usará como referencia de paleta. La
implementación añadirá tokens propios a Fuente, en lugar de copiar el proyecto
completo. Si se reutiliza un archivo del repositorio Nord, se conservarán sus
avisos y condiciones Apache-2.0; sus materiales documentales y visuales no se
copiarán por defecto.

Los tokens mínimos son:

| Uso | Token Fuente | Valor Nord |
|---|---|---|
| Fondo principal | `--fuente-polar-0` | `#2E3440` |
| Superficie | `--fuente-polar-1` | `#3B4252` |
| Borde | `--fuente-polar-2` | `#434C5E` |
| Texto principal | `--fuente-snow-2` | `#ECEFF4` |
| Texto secundario | `--fuente-snow-0` | `#D8DEE9` |
| Acción y foco | `--fuente-frost-2` | `#81A1C1` |
| Acción secundaria | `--fuente-frost-1` | `#88C0D0` |
| Éxito | `--fuente-success` | `#A3BE8C` |
| Aviso | `--fuente-warning` | `#EBCB8B` |
| Error | `--fuente-danger` | `#BF616A` |

Botones, paneles, modales, formularios, estados de cola, grafo y lector deben
consumir tokens semánticos, no valores hexadecimales aislados. El diseño debe
mantener foco visible por teclado, contraste suficiente, estados de error
legibles sin depender solo del color y reducción de movimiento cuando el
sistema lo solicite.

El lector conserva el diseño de tres zonas: nota a la izquierda; propiedades a
la derecha arriba; grafo local a la derecha abajo. En pantallas estrechas, las
tres zonas se apilan o se presentan como pestañas sin ocultar información.

## 7. Política de IA ultra-ligera

`qwen3.5:0.8b` queda designado como primera elección del nivel Auto
ultra-ligero, condicionado al benchmark. El catálogo mantendrá
`qwen2.5:0.5b` como alternativa de compatibilidad y BM25 como degradación si
no cabe ningún LLM en la holgura medida.

La selección requiere a la vez: memoria disponible medida, margen de seguridad
del 35 %, modelo exacto instalado localmente, contexto limitado a 4.096 tokens
y una única generación concurrente. Si falla cualquiera de estas condiciones,
Fuente no lo descarga ni lo fuerza: elige la alternativa que quepa o BM25.

El benchmark se ejecutará con el mismo conjunto de documentos aprobados de
`3_limpio` para `qwen3.5:0.8b` y `qwen2.5:0.5b`. Medirá memoria, latencia y
calidad de la salida en español. Una salida es válida solo si supera la
validación estructural, conserva las referencias a los orígenes y no inventa
afirmaciones que no aparezcan en ellos. La promoción exige mantener la holgura
configurada y no empeorar esos resultados frente a la alternativa actual.

## 8. Condiciones de aceptación

- Ningún sumario se genera, actualiza, indexa como vigente ni exporta si alguno
  de sus orígenes no corresponde a una revisión aprobada de `3_limpio`.
- Todo Markdown en `3_limpio` requiere aprobación humana explícita ligada a su
  revisión y hash exactos antes de poder producir derivados. Todo Markdown en
  `4_salida` requiere además una aprobación humana propia antes de considerarse
  publicado, exportable o disponible como resultado editorial. La aprobación de
  `4_salida` nunca sustituye la aprobación canónica de `3_limpio`.
- Cambiar un documento aprobado invalida esa aprobación y marca los derivados
  afectados como desactualizados.
- Desde un sumario, una persona puede abrir el origen exacto y saber qué
  revisión aprobada lo respaldó.
- Un catálogo, grafo o índice eliminado se reconstruye desde Markdown sin
  cambiar el contenido de `3_limpio`.
- Tras la migración completa, los nuevos datos y pantallas no crean
  `Fuente`, `.fuente`, `Fuentes`, `source_kind` ni `sources`; las apariciones
  restantes están limitadas al lector de compatibilidad, los manifiestos de
  migración y la documentación histórica.
- La consola usa los tokens Fuente derivados de Nord de forma consistente y
  conserva sus contratos de seguridad y accesibilidad.
- `qwen3.5:0.8b` no se convierte en selección efectiva hasta que el benchmark
  local confirme memoria, latencia y calidad bajo `num_ctx=4096`; antes de ese
  momento conserva el estado de candidato predeterminado en el plan.
