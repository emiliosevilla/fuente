# Estilo visual de Fuente

Referencia de diseño para la consola de Fuente y sus interfaces asociadas.

Fuente ofrece **dos estilos visuales claros e independientes**, seleccionables
por el usuario:

- **Zen** — azul profundo, frío y concentrado.
- **Energy** — naranja vivo, cálido y activo.

No son dos acentos dentro de una misma paleta. Cada estilo define su propio
fondo, superficies, bordes, acento, estados y tratamiento de selección. Ambos
comparten únicamente las reglas de legibilidad, estructura y comportamiento.

Este documento es la referencia objetivo de Fuente. No debe confundirse con
los temas del Vault (`General`, `Derecho_Civil`, etc.), que son otra capa del
producto.

---

## Selector de estilo visual

La consola debe mostrar un selector visible con exactamente estas opciones:

| Valor | Etiqueta | Carácter |
|---|---|---|
| `zen` | Zen 🧘 | Calmado, concentrado, azul profundo |
| `energy` | Energy ⚡ | Activo, cálido, naranja vivo |

Reglas del selector:

- Está disponible en la cabecera de la consola y también es accesible desde
  Ajustes.
- Cambia el estilo visual completo sin cambiar el Vault, el tema de notas ni
  la configuración del ETL.
- La selección se aplica inmediatamente y se conserva entre sesiones.
- La preferencia persistida usa el valor estable `zen` o `energy`, nunca el
  texto traducido de la etiqueta.
- Debe tener foco visible, navegación por teclado y anunciar el estilo activo.
- El selector visual debe tener una identidad distinta del selector de temas
  del Vault.

Contrato recomendado para la implementación:

```html
<html data-fuente-style="zen">
```

La interfaz puede usar `data-fuente-style="zen"` o
`data-fuente-style="energy"` como raíz para activar el conjunto de tokens
correspondiente.

---

## Modo Zen 🧘 — Azul profundo

Zen es el modo recomendado para lectura, revisión editorial y trabajo
prolongado. Debe sentirse silencioso, estable y ordenado.

### Paleta y tokens

| Token | Hex / valor | Uso |
|---|---|---|
| `bg-app` | `#ced3da` | Fondo general de la consola |
| `border-app` | `#9ea4ae` | Borde exterior y separadores neutros |
| `header-bg` | `#1E4FA0` | Cabecera y áreas de navegación principales |
| `header-border` | `#163D80` | Borde de cabecera |
| `header-logo` | `#ffffff` | Marca y texto sobre la cabecera |
| `header-btn-bg` | `rgba(0,0,0,.15)` | Fondo de controles de cabecera |
| `header-btn-border` | `rgba(0,0,0,.25)` | Borde de controles de cabecera |
| `header-btn-color` | `#ffffff` | Texto de controles de cabecera |
| `sidebar-bg` | `#c4c9d2` | Navegación lateral, si existe |
| `sidebar-border` | `#1E4FA0` | Borde de navegación lateral |
| `sidebar-section` | `#4a5060` | Etiquetas de sección |
| `sidebar-item` | `#2c3040` | Texto de elementos inactivos |
| `sidebar-active-color` | `#1E4FA0` | Elemento activo |
| `sidebar-active-bg` | `#eef3ff` | Fondo del elemento activo |
| `surface` | `#f5f7fa` | Tarjetas, lector y superficies claras |
| `surface-raised` | `#dce0e8` | Paneles elevados y modales |
| `surface-input` | `#ebeef5` | Campos dentro de modales |
| `text-primary` | `#13151a` | Texto principal |
| `text-secondary` | `#4a5060` | Texto auxiliar y etiquetas |
| `accent` | `#1E4FA0` | Acento, foco y acciones activas |
| `accent-strong` | `#163D80` | Acento de contraste y bordes fuertes |
| `accent-soft` | `#dce8ff` | Selección y fondos de énfasis |
| `node-border` | `#7a8090` | Bordes del árbol o grafo |
| `connector` | `#7a8090` | Líneas del árbol o grafo |
| `shadow-selected` | `rgba(30,79,160,.28)` | Sombra de selección |

### Estados Zen

| Estado | Fondo | Borde / texto |
|---|---|---|
| Éxito | `#e2f0d4` | `#4a6e2a` / `#2a4a0e` |
| Aviso | `#e8f0fe` | `#163D80` / `#0d2055` |
| Error | `#fce8e8` | `#9e2a2a` / `#4a1010` |
| Seleccionado | `#dce8ff` | `#1E4FA0` |
| Foco de teclado | transparente | `#1E4FA0`, mínimo 2 px |

---

## Modo Energy ⚡ — Naranja vivo

Energy es el modo recomendado para operación, ingesta y seguimiento de
actividad. Debe sentirse luminoso, directo y con más impulso visual.

### Paleta y tokens

| Token | Hex / valor | Uso |
|---|---|---|
| `bg-app` | `#d6d5d0` | Fondo general de la consola |
| `border-app` | `#9e9d99` | Borde exterior y separadores neutros |
| `header-bg` | `#d97757` | Cabecera y áreas de navegación principales |
| `header-border` | `#c06040` | Borde de cabecera |
| `header-logo` | `#ffffff` | Marca y texto sobre la cabecera |
| `header-btn-bg` | `rgba(0,0,0,.13)` | Fondo de controles de cabecera |
| `header-btn-border` | `rgba(0,0,0,.22)` | Borde de controles de cabecera |
| `header-btn-color` | `#ffffff` | Texto de controles de cabecera |
| `sidebar-bg` | `#cbc9c4` | Navegación lateral, si existe |
| `sidebar-border` | `#d97757` | Borde de navegación lateral |
| `sidebar-section` | `#5f5e5a` | Etiquetas de sección |
| `sidebar-item` | `#2c2c2a` | Texto de elementos inactivos |
| `sidebar-active-color` | `#d97757` | Elemento activo |
| `sidebar-active-bg` | `#fff3ef` | Fondo del elemento activo |
| `surface` | `#ffffff` | Tarjetas, lector y superficies claras |
| `surface-raised` | `#e8e7e2` | Paneles elevados y modales |
| `surface-input` | `#f5f4f0` | Campos dentro de modales |
| `text-primary` | `#141413` | Texto principal |
| `text-secondary` | `#5f5e5a` | Texto auxiliar y etiquetas |
| `accent` | `#d97757` | Acento, foco y acciones activas |
| `accent-strong` | `#c06040` | Acento de contraste y bordes fuertes |
| `accent-soft` | `#fff3ef` | Selección y fondos de énfasis |
| `node-border` | `#7a7975` | Bordes del árbol o grafo |
| `connector` | `#7a7975` | Líneas del árbol o grafo |
| `shadow-selected` | `rgba(217,119,87,.30)` | Sombra de selección |

### Estados Energy

| Estado | Fondo | Borde / texto |
|---|---|---|
| Éxito | `#e2f0d4` | `#4a6e2a` / `#2a4a0e` |
| Aviso | `#fdeee6` | `#c06040` / `#5a2a10` |
| Error | `#fce8e8` | `#9e2a2a` / `#4a1010` |
| Seleccionado | `#fff3ef` | `#d97757` |
| Foco de teclado | transparente | `#d97757`, mínimo 2 px |

---

## Componentes de Fuente

Los componentes conservan la misma estructura en ambos modos; solo cambia el
conjunto de tokens activo.

### Cabecera y navegación

- La cabecera usa `header-bg` y texto claro de alto contraste.
- El selector `Zen / Energy` es visible y no se confunde con el selector de
  temas del Vault.
- Los controles de navegación usan estados `default`, `hover`, `active`,
  `disabled` y `focus-visible`.
- El logo y los nombres de Fuente mantienen el mismo peso visual en ambos
  estilos.

### Barra de estado y tarjetas

- La barra de estado comunica modo de red, salud, cola y actividad ETL.
- Las tarjetas usan `surface`, `text-primary` y `border-app`.
- La elevación se expresa con una sombra discreta; no se usan degradados ni
  sombras decorativas fuertes.
- Los números o métricas importantes pueden usar `accent`, `success`, `warning`
  o `danger`, siempre con una etiqueta textual complementaria.

### Árbol, grafo y notas

- El fondo del árbol usa `surface` y los conectores usan `connector`.
- El elemento seleccionado usa `accent-soft` y `accent`; no cambia
  arbitrariamente el color del texto.
- Las tarjetas de notas, temas e incidencias no deben parecer botones si no
  son accionables.
- El lector prioriza el texto y el espacio; Energy puede aportar énfasis en
  acciones, pero no convertir la lectura en una pantalla de alertas.

### Editor, formularios y modales

- Las etiquetas usan `text-secondary`; el contenido introducido usa
  `text-primary`.
- Los campos usan `surface-input`, un borde visible y un foco de teclado claro.
- Los modales usan `surface-raised`, borde `accent-strong` y título
  `text-primary`.
- El modal de Ajustes conserva su responsabilidad funcional y puede incluir el
  selector visual, pero no debe mezclarse con la configuración del Vault ni
  con el selector de temas de conocimiento.

### Botones

| Variante | Regla |
|---|---|
| Primario | Fondo `text-primary`, texto `surface`; reservado para la acción principal |
| Secundario | Fondo transparente o `surface`, borde `accent-strong` |
| Activo | Fondo `accent-soft`, texto `accent-strong` |
| Peligro | Usa el conjunto de estado `danger`; nunca depende solo del color |
| Deshabilitado | Reduce contraste y elimina interacción; conserva legibilidad |

### Logs, avisos y errores

- Los logs usan una tipografía monoespaciada y una superficie de lectura
  estable.
- Cada aviso combina color, icono o símbolo y texto.
- Éxito, aviso y error conservan el significado entre Zen y Energy; solo cambia
  la expresión de los avisos no críticos según la tabla de cada modo.

---

## Reglas compartidas

- Ambos estilos son claros. No hay modo oscuro dentro de esta especificación.
- No usar texto blanco sobre fondos slate claros. El blanco se reserva para
  texto sobre `header-bg` u otro fondo de acento suficientemente contrastado.
- Los bordes de sección usan el acento del modo activo cuando expresan
  estructura o selección.
- El color nunca es la única señal de estado: acompáñalo con texto, icono,
  forma o posición.
- El foco de teclado debe ser visible en ambos modos y no puede eliminarse por
  razones estéticas.
- Se permite un efecto glass controlado para separar superficies: translucencia
  moderada, desenfoque progresivo y sombras suaves. No usar neón ni efectos que
  reduzcan el contraste; el movimiento debe ser sutil y respetar
  `prefers-reduced-motion`.
- La consola y sus modales usan Arial; los logs y el código pueden conservar
  una tipografía monoespaciada cuando el contexto lo requiera.
- El cambio de estilo no modifica datos, rutas, temas del Vault, jobs ni
  comportamiento del ETL.
- Los tokens deben tener nombres semánticos y no nombres ligados a un color,
  por ejemplo `accent` en lugar de `orange` o `navy`.

## Diferencia frente al estilo Nord actual

La implementación actual de Fuente conserva tokens inspirados en Nord en
`fuente/ui/static/fuente_tokens.css`. Este documento define la dirección visual
nueva: dos estilos claros, `Zen` y `Energy`, con selector persistente. La
migración de los tokens y la implementación del selector deben hacerse como un
cambio posterior verificable; esta guía no afirma que esa migración ya esté
completada.
