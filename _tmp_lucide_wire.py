#!/usr/bin/env python3
"""Wire Lucide icons into consola_preview.html — one-shot helper."""
from __future__ import annotations

import re
from pathlib import Path

html_path = Path("consola_preview.html")
text = html_path.read_text(encoding="utf-8")


def lucide_body(name: str) -> str:
    raw = Path(f"/tmp/lucide-{name}.svg").read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    inner = re.sub(r"^<svg[^>]*>", "", raw.strip(), count=1, flags=re.S)
    inner = re.sub(r"</svg>\s*$", "", inner).strip()
    return inner.replace(" />", ">")


alias = {
    "house": "house",
    "library": "library",
    "waves": "waves",
    "sun-moon": "sun-moon",
    "settings-2": "settings-2",
    "book-open": "book-open",
    "filter": "filter",
    "arrow-up-down": "arrow-up-down",
    "ellipsis": "ellipsis",
    "message-circle": "message-circle",
    "back": "chevron-left",
    "search": "search",
    "close": "x",
    "chevron-down": "chevron-down",
    "chevron-left": "chevron-left",
    "chevron-right": "chevron-right",
    "download": "download",
    "upload": "upload",
    "copy": "copy",
    "printer": "printer",
    "share-2": "share-2",
    "external-link": "external-link",
    "plus": "plus",
    "minus": "minus",
    "file": "file",
    "folder": "folder",
    "folder-open": "folder-open",
    "layout-grid": "layout-grid",
    "list": "list",
    "file-text": "file-text",
    "newspaper": "newspaper",
    "palette": "palette",
    "activity": "activity",
    "eraser": "eraser",
    "trash-2": "trash-2",
    "check": "check",
    "sparkles": "sparkles",
    "send": "send",
    "panel-left-close": "panel-left-close",
    "file-plus": "file-plus",
    "heart-pulse": "heart-pulse",
    "scroll-text": "scroll-text",
    "folder-search": "folder-search",
    "save": "save",
    "rotate-ccw": "rotate-ccw",
    "file-code": "file-code",
    "zap": "zap",
    "refresh-cw": "refresh-cw",
    "circle-check": "circle-check",
    "wand-sparkles": "wand-sparkles",
    "network": "network",
    "layers": "layers",
    "file-type": "file-type",
    "git-branch": "git-branch",
    "cloud": "cloud",
    "link": "link",
    "eye": "eye",
}

defs_parts = [
    '    <svg id="ui-icon-definitions" aria-hidden="true" focusable="false">',
    "        <defs>",
    "            <!-- Lucide stroke icons; CSS sets stroke on svg.ui-icon -->",
]
for uid, lucide_name in alias.items():
    body = lucide_body(lucide_name)
    indented = "\n".join(
        ("                " + line.lstrip()) if line.strip() else ""
        for line in body.splitlines()
    )
    defs_parts.append(f'            <symbol id="ui-icon-{uid}" viewBox="0 0 24 24">')
    defs_parts.append(indented)
    defs_parts.append("            </symbol>")
defs_parts.extend(["        </defs>", "    </svg>"])
new_defs = "\n".join(defs_parts)

text, n = re.subn(
    r'<svg id="ui-icon-definitions"[\s\S]*?</svg>\n',
    new_defs + "\n",
    text,
    count=1,
)
assert n == 1, n


def icon(name: str) -> str:
    return (
        f'<svg class="ui-icon" aria-hidden="true" focusable="false">'
        f'<use href="#ui-icon-{name}"></use></svg>'
    )


INLINE_MAP = {
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"></path></svg>': icon(
        "chevron-down"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"></path></svg>': icon(
        "close"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-4-4"></path></svg>': icon(
        "search"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="m15 5-7 7 7 7"></path></svg>': icon(
        "chevron-left"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7"></path></svg>': icon(
        "chevron-right"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 16V3m0 0L7 8m5-5 5 5M4 14v6h16v-6"></path></svg>': icon(
        "download"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 3v13m0 0-5-5m5 5 5-5M4 20h16"></path></svg>': icon(
        "upload"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M4 5h16l-6 7v6l-4 2v-8z"></path></svg>': icon(
        "filter"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="1"></rect><path d="M5 15H4V4h11v1"></path></svg>': icon(
        "copy"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M6 9V3h12v6M6 18H4v-8h16v8h-2M7 14h10v7H7z"></path></svg>': icon(
        "printer"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M5 12h12m-4-4 4 4-4 4M19 5v14"></path></svg>': icon(
        "upload"
    ),
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="m12 3 6 5-6 13-6-13z"></path><path d="m6 8 6 4 6-4"></path></svg>': icon(
        "external-link"
    ),
}

for old, new in INLINE_MAP.items():
    c = text.count(old)
    if c == 0:
        print("WARN no match for inline:", old[:90])
    text = text.replace(old, new)

# Exact one-shot button injections
pairs: list[tuple[str, str]] = [
    (
        '<button type="button" class="btn-secondary" data-onclick-command="promptCreateTheme()">Nuevo tema</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="promptCreateTheme()">{icon("file-plus")}Nuevo tema</button>',
    ),
    (
        '<button type="button" class="btn-secondary" id="btn-open-health" data-onclick-command="openModal(\'modal-health\')">Estado del sistema</button>',
        f'<button type="button" class="btn-secondary" id="btn-open-health" data-onclick-command="openModal(\'modal-health\')">{icon("heart-pulse")}Estado del sistema</button>',
    ),
    (
        '<button class="btn-small" id="btn-toggle-path" data-onclick-command="togglePathMode(this)">Rutas cortas</button>',
        f'<button class="btn-small" id="btn-toggle-path" data-onclick-command="togglePathMode(this)">{icon("folder")}Rutas cortas</button>',
    ),
    (
        '<button class="btn-small" data-onclick-command="clearLogView()">Limpiar</button>',
        f'<button class="btn-small" data-onclick-command="clearLogView()">{icon("eraser")}Limpiar</button>',
    ),
    (
        '<button type="button" class="source-view-tab" id="btn-source-view-grid" role="tab" data-onclick-command="switchSourceView(\'grid\')">Grid</button>',
        f'<button type="button" class="source-view-tab" id="btn-source-view-grid" role="tab" data-onclick-command="switchSourceView(\'grid\')">{icon("layout-grid")}<span>Grid</span></button>',
    ),
    (
        '<button type="button" class="source-view-tab is-active" id="btn-source-view-list" role="tab" aria-selected="true" data-onclick-command="switchSourceView(\'list\')">Lista</button>',
        f'<button type="button" class="source-view-tab is-active" id="btn-source-view-list" role="tab" aria-selected="true" data-onclick-command="switchSourceView(\'list\')">{icon("list")}<span>Lista</span></button>',
    ),
    (
        '<button type="button" class="source-view-tab" id="btn-source-view-individual" role="tab" data-onclick-command="switchSourceView(\'individual\')">Individual</button>',
        f'<button type="button" class="source-view-tab" id="btn-source-view-individual" role="tab" data-onclick-command="switchSourceView(\'individual\')">{icon("file-text")}<span>Individual</span></button>',
    ),
    (
        '<button type="button" class="source-view-tab" id="btn-source-view-feed" role="tab" data-onclick-command="switchSourceView(\'feed\')">Feed</button>',
        f'<button type="button" class="source-view-tab" id="btn-source-view-feed" role="tab" data-onclick-command="switchSourceView(\'feed\')">{icon("newspaper")}<span>Feed</span></button>',
    ),
    (
        """                    <div class="reader-actions" id="fuente-reader-actions">
                        <button type="button" data-onclick-command="triggerAction('copy_reader_note', {}, this)">Copiar</button>
                        <button type="button" data-onclick-command="printCurrentNote()">Imprimir</button>
                        <button type="button" data-onclick-command="triggerAction('export_reader_note', {}, this)">Exportar</button>
                        <button type="button" data-onclick-command="triggerAction('open_obsidian', {}, this)">Abrir en Obsidian</button>
                    </div>""",
        f"""                    <div class="reader-actions" id="fuente-reader-actions">
                        <button type="button" class="btn-small" data-onclick-command="triggerAction('copy_reader_note', {{}}, this)">{icon("copy")}Copiar</button>
                        <button type="button" class="btn-small" data-onclick-command="printCurrentNote()">{icon("printer")}Imprimir</button>
                        <button type="button" class="btn-small" data-onclick-command="triggerAction('export_reader_note', {{}}, this)">{icon("upload")}Exportar</button>
                        <button type="button" class="btn-small" data-onclick-command="triggerAction('open_obsidian', {{}}, this)">{icon("external-link")}Abrir en Obsidian</button>
                    </div>""",
    ),
    (
        '<button type="button" class="vertical-tab fuente-chat-tab" data-onclick-command="openDrawer(\'source-chat-drawer\')" aria-label="Abrir consulta local">‹  Consultar local</button>',
        f'<button type="button" class="vertical-tab fuente-chat-tab" data-onclick-command="openDrawer(\'source-chat-drawer\')" aria-label="Abrir consulta local">{icon("message-circle")} Consultar local</button>',
    ),
    (
        '<button type="button" class="toolbar-button">Filtros</button>',
        f'<button type="button" class="toolbar-button">{icon("filter")}Filtros</button>',
    ),
    (
        '<button type="button" class="toolbar-button">Limpiar filtros</button>',
        f'<button type="button" class="toolbar-button">{icon("eraser")}Limpiar filtros</button>',
    ),
    (
        '<div class="graph-controls"><span><button type="button">-</button><button type="button">100%</button><button type="button">+</button></span><button type="button" class="btn-secondary" data-onclick-command="openObsidianGraph()">Abrir grafo completo en Obsidian</button></div>',
        f'<div class="graph-controls"><span><button type="button" class="icon-button" aria-label="Alejar">{icon("minus")}</button><button type="button" class="btn-small">100%</button><button type="button" class="icon-button" aria-label="Acercar">{icon("plus")}</button></span><button type="button" class="btn-secondary" data-onclick-command="openObsidianGraph()">{icon("network")}Abrir grafo completo en Obsidian</button></div>',
    ),
    (
        '<button type="button" class="btn-primary shell-primary-action" hidden data-onclick-command="triggerAction(\'step2_transcribe\')">Procesar material</button>',
        f'<button type="button" class="btn-primary shell-primary-action" hidden data-onclick-command="triggerAction(\'step2_transcribe\')">{icon("sparkles")}Procesar material</button>',
    ),
    (
        '<button type="button" data-onclick-command="runCaudalImport(\'files\')">Archivos</button>',
        f'<button type="button" data-onclick-command="runCaudalImport(\'files\')">{icon("file")}Archivos</button>',
    ),
    (
        '<button type="button" data-onclick-command="runCaudalImport(\'folder\')">Carpeta</button>',
        f'<button type="button" data-onclick-command="runCaudalImport(\'folder\')">{icon("folder")}Carpeta</button>',
    ),
    (
        '<button type="button" data-onclick-command="runCaudalImport(\'sync\')">SharePoint sincronizado</button>',
        f'<button type="button" data-onclick-command="runCaudalImport(\'sync\')">{icon("cloud")}SharePoint sincronizado</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="openDrawer(\'flow-log-drawer\')">Ver registro</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="openDrawer(\'flow-log-drawer\')">{icon("scroll-text")}Ver registro</button>',
    ),
    (
        '<button type="button" class="btn-primary" id="btn-caudal-approve-step" data-onclick-command="approveCaudalSelection()">Aprobar paso</button>',
        f'<button type="button" class="btn-primary" id="btn-caudal-approve-step" data-onclick-command="approveCaudalSelection()">{icon("circle-check")}Aprobar paso</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="switchWorkspace(\'source\')">Abrir en Fuente</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="switchWorkspace(\'source\')">{icon("library")}Abrir en Fuente</button>',
    ),
    (
        '<button class="btn-secondary" data-onclick-command="openModal(\'modal-job-queue\')">Abrir cola completa</button>',
        f'<button class="btn-secondary" data-onclick-command="openModal(\'modal-job-queue\')">{icon("layers")}Abrir cola completa</button>',
    ),
    (
        '<button type="button" class="vertical-tab activity-tab" data-onclick-command="openDrawer(\'flow-log-drawer\')" aria-label="Abrir registro de actividad">Registro de actividad  ›</button>',
        f'<button type="button" class="vertical-tab activity-tab" data-onclick-command="openDrawer(\'flow-log-drawer\')" aria-label="Abrir registro de actividad">{icon("activity")} Registro de actividad</button>',
    ),
    (
        '<button class="btn-small" id="btn-reader-library" aria-pressed="true" data-onclick-command="toggleReaderLibrary()">Biblioteca</button>',
        f'<button class="btn-small" id="btn-reader-library" aria-pressed="true" data-onclick-command="toggleReaderLibrary()">{icon("panel-left-close")}Biblioteca</button>',
    ),
    (
        '<button class="btn-small" id="btn-reader-context" aria-pressed="false" data-onclick-command="toggleReaderContext()">Contexto</button>',
        f'<button class="btn-small" id="btn-reader-context" aria-pressed="false" data-onclick-command="toggleReaderContext()">{icon("message-circle")}Contexto</button>',
    ),
    (
        '<button type="button" class="btn-small source-view-tab" id="btn-source-view-filtered" role="tab" data-onclick-command="switchSourceView(\'filtered\')">Filtrada</button>',
        f'<button type="button" class="btn-small source-view-tab" id="btn-source-view-filtered" role="tab" data-onclick-command="switchSourceView(\'filtered\')">{icon("filter")}Filtrada</button>',
    ),
    (
        '<button type="button" class="btn-small" id="btn-source-hierarchy" data-onclick-command="switchSourceView(\'hierarchy\')">Jerarquía</button>',
        f'<button type="button" class="btn-small" id="btn-source-hierarchy" data-onclick-command="switchSourceView(\'hierarchy\')">{icon("git-branch")}Jerarquía</button>',
    ),
    (
        '<button type="button" class="btn-small" id="btn-source-relations" data-onclick-command="switchSourceView(\'relations\')">Relaciones</button>',
        f'<button type="button" class="btn-small" id="btn-source-relations" data-onclick-command="switchSourceView(\'relations\')">{icon("network")}Relaciones</button>',
    ),
    (
        '<button type="button" class="btn-small" data-onclick-command="openDrawer(\'source-search-drawer\')">Buscar</button>',
        f'<button type="button" class="btn-small" data-onclick-command="openDrawer(\'source-search-drawer\')">{icon("search")}Buscar</button>',
    ),
    (
        '<div class="library-head"><h2 class="reader-sidebar-divider">Biblioteca</h2><button type="button" class="icon-button" data-onclick-command="toggleReaderLibrary()" aria-label="Plegar biblioteca">«</button></div>',
        f'<div class="library-head"><h2 class="reader-sidebar-divider">Biblioteca</h2><button type="button" class="icon-button" data-onclick-command="toggleReaderLibrary()" aria-label="Plegar biblioteca">{icon("panel-left-close")}</button></div>',
    ),
    (
        '<button type="button" class="btn-secondary" id="btn-open-obsidian-graph" data-onclick-command="openObsidianGraph()">Abrir grafo completo en Obsidian</button>',
        f'<button type="button" class="btn-secondary" id="btn-open-obsidian-graph" data-onclick-command="openObsidianGraph()">{icon("network")}Abrir grafo completo en Obsidian</button>',
    ),
    (
        '<button type="button" class="btn-primary" id="document-share-button" disabled>Compartir nota</button>',
        f'<button type="button" class="btn-primary" id="document-share-button" disabled>{icon("share-2")}Compartir nota</button>',
    ),
    (
        '<button type="button" class="btn-primary" data-onclick-command="runSourceSearch()">Buscar</button>',
        f'<button type="button" class="btn-primary" data-onclick-command="runSourceSearch()">{icon("search")}Buscar</button>',
    ),
    (
        '<button type="button" class="btn-small" data-onclick-command="openCurrentNoteFile()">Abrir archivo</button>',
        f'<button type="button" class="btn-small" data-onclick-command="openCurrentNoteFile()">{icon("folder-open")}Abrir archivo</button>',
    ),
    (
        '<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'filtered\')">Filtrada</button>',
        f'<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'filtered\')">{icon("filter")}Filtrada</button>',
    ),
    (
        '<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'hierarchy\')">Jerarquía</button>',
        f'<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'hierarchy\')">{icon("git-branch")}Jerarquía</button>',
    ),
    (
        '<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'relations\')">Relaciones</button>',
        f'<button type="button" class="btn-small" data-onclick-command="switchSourceView(\'relations\')">{icon("network")}Relaciones</button>',
    ),
    (
        '<button class="btn-secondary" data-onclick-command="closeModal(\'modal-create-theme\')">Cancelar</button>',
        f'<button class="btn-secondary" data-onclick-command="closeModal(\'modal-create-theme\')">{icon("close")}Cancelar</button>',
    ),
    (
        '<button class="btn-primary" data-onclick-command="submitCreateThemeModal()">Crear tema</button>',
        f'<button class="btn-primary" data-onclick-command="submitCreateThemeModal()">{icon("check")}Crear tema</button>',
    ),
    (
        """                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('markdown')">
                        Texto (.md)
                    </button>
                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('pdf')">
                        Imprimir / Guardar como PDF
                    </button>
                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('docx')">
                        Word (.docx)
                    </button>""",
        f"""                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('markdown')">
                        {icon("file-code")}Texto (.md)
                    </button>
                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('pdf')">
                        {icon("printer")}Imprimir / Guardar como PDF
                    </button>
                    <button class="btn-primary console-layout-023" data-onclick-command="executeExportFormat('docx')">
                        {icon("file-type")}Word (.docx)
                    </button>""",
    ),
    (
        '<button class="btn-secondary" data-onclick-command="closeModal(\'modal-export-options\')">Cancelar</button>',
        f'<button class="btn-secondary" data-onclick-command="closeModal(\'modal-export-options\')">{icon("close")}Cancelar</button>',
    ),
    (
        '<button class="btn-secondary console-layout-031" data-onclick-command="triggerAction(\'stat_ram\')">Liberar memoria</button>',
        f'<button class="btn-secondary console-layout-031" data-onclick-command="triggerAction(\'stat_ram\')">{icon("zap")}Liberar memoria</button>',
    ),
    (
        '<button class="btn-secondary" id="setup-install-obsidian" data-onclick-command="installObsidian()">Instalar Obsidian</button>',
        f'<button class="btn-secondary" id="setup-install-obsidian" data-onclick-command="installObsidian()">{icon("download")}Instalar Obsidian</button>',
    ),
    (
        '<button class="btn-secondary" id="setup-create-vault" data-onclick-command="createGuidedVault()">Crear Vault Fuente</button>',
        f'<button class="btn-secondary" id="setup-create-vault" data-onclick-command="createGuidedVault()">{icon("folder-open")}Crear Vault Fuente</button>',
    ),
    (
        '<button class="btn-secondary console-layout-037" data-onclick-command="browseVaultFolder()">Explorar...</button>',
        f'<button class="btn-secondary console-layout-037" data-onclick-command="browseVaultFolder()">{icon("folder-search")}Explorar...</button>',
    ),
    (
        '<button class="btn-small" data-onclick-command="addLinkedInputFolder()">+ Añadir carpeta</button>',
        f'<button class="btn-small" data-onclick-command="addLinkedInputFolder()">{icon("plus")}Añadir carpeta</button>',
    ),
    (
        '<button class="btn-small" data-onclick-command="addLinkedOutputFolder()">+ Añadir destino</button>',
        f'<button class="btn-small" data-onclick-command="addLinkedOutputFolder()">{icon("plus")}Añadir destino</button>',
    ),
    (
        '<button type="button" class="btn-secondary console-layout-037" data-onclick-command="browseWhisperModelFolder()">Explorar...</button>',
        f'<button type="button" class="btn-secondary console-layout-037" data-onclick-command="browseWhisperModelFolder()">{icon("folder-search")}Explorar...</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="openModal(\'modal-template-helper\')">Abrir editor de plantillas</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="openModal(\'modal-template-helper\')">{icon("file-text")}Abrir editor de plantillas</button>',
    ),
    (
        '<button class="btn-secondary console-text-018" data-onclick-command="resetDefaultSettings()">Restablecer valores</button>',
        f'<button class="btn-secondary console-text-018" data-onclick-command="resetDefaultSettings()">{icon("rotate-ccw")}Restablecer valores</button>',
    ),
    (
        '<button class="btn-secondary console-text-020" data-onclick-command="saveSettings()">Guardar</button>',
        f'<button class="btn-secondary console-text-020" data-onclick-command="saveSettings()">{icon("save")}Guardar</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="restoreTemplateHelper()">Restaurar</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="restoreTemplateHelper()">{icon("rotate-ccw")}Restaurar</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="previewTemplateHelper()">Previsualizar</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="previewTemplateHelper()">{icon("eye")}Previsualizar</button>',
    ),
    (
        '<button type="button" class="btn-primary" data-onclick-command="saveTemplateHelper()">Guardar cambios</button>',
        f'<button type="button" class="btn-primary" data-onclick-command="saveTemplateHelper()">{icon("save")}Guardar cambios</button>',
    ),
    (
        '<button class="btn-primary" id="btn-approve-note" data-onclick-command="approveSelectedNote()" disabled>Dar por buena</button>',
        f'<button class="btn-primary" id="btn-approve-note" data-onclick-command="approveSelectedNote()" disabled>{icon("circle-check")}Dar por buena</button>',
    ),
    (
        '<button class="btn-primary" id="btn-approve-export" data-onclick-command="approveAndExportSelectedNote()" disabled>Dar por buena y sacar</button>',
        f'<button class="btn-primary" id="btn-approve-export" data-onclick-command="approveAndExportSelectedNote()" disabled>{icon("upload")}Dar por buena y sacar</button>',
    ),
    (
        '<button class="btn-secondary" id="btn-retry-approval-export" data-onclick-command="retryFailedApprovalExport()" hidden>Intentar de nuevo</button>',
        f'<button class="btn-secondary" id="btn-retry-approval-export" data-onclick-command="retryFailedApprovalExport()" hidden>{icon("refresh-cw")}Intentar de nuevo</button>',
    ),
    (
        '<button type="button" data-onclick-command="openModal(\'modal-caudal-export\')">Exportar</button>',
        f'<button type="button" data-onclick-command="openModal(\'modal-caudal-export\')">{icon("upload")}Exportar</button>',
    ),
    (
        '<div class="source-choice"><b>Archivos</b><p>Importa archivos individuales (md, txt, pdf, docx, etc.).</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'files\')">Elegir...</button></div>',
        f'<div class="source-choice"><b>Archivos</b><p>Importa archivos individuales (md, txt, pdf, docx, etc.).</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'files\')">{icon("folder-search")}Elegir...</button></div>',
    ),
    (
        '<div class="source-choice"><b>Carpeta</b><p>Importa todos los archivos de una carpeta.</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'folder\')">Elegir...</button></div>',
        f'<div class="source-choice"><b>Carpeta</b><p>Importa todos los archivos de una carpeta.</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'folder\')">{icon("folder-search")}Elegir...</button></div>',
    ),
    (
        '<div class="source-choice"><b>SharePoint sincronizado</b><p>Importa desde una biblioteca o carpeta de SharePoint.</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'sync\')">Elegir...</button></div>',
        f'<div class="source-choice"><b>SharePoint sincronizado</b><p>Importa desde una biblioteca o carpeta de SharePoint.</p><button type="button" class="btn-secondary" data-onclick-command="runCaudalImport(\'sync\')">{icon("folder-search")}Elegir...</button></div>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="closeModal(\'modal-caudal-import\')">Cancelar</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="closeModal(\'modal-caudal-import\')">{icon("close")}Cancelar</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="closeModal(\'modal-caudal-import\')">Atrás</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="closeModal(\'modal-caudal-import\')">{icon("back")}Atrás</button>',
    ),
    (
        '<button type="button" class="btn-primary" data-onclick-command="closeModal(\'modal-caudal-import\')">Continuar</button>',
        f'<button type="button" class="btn-primary" data-onclick-command="closeModal(\'modal-caudal-import\')">{icon("chevron-right")}Continuar</button>',
    ),
    (
        '<button type="button" class="btn-primary" data-onclick-command="runCaudalExport()">Exportar</button>',
        f'<button type="button" class="btn-primary" data-onclick-command="runCaudalExport()">{icon("upload")}Exportar</button>',
    ),
    (
        '<button type="button" class="btn-secondary" data-onclick-command="downloadPdfFile()">Imprimir PDF</button>',
        f'<button type="button" class="btn-secondary" data-onclick-command="downloadPdfFile()">{icon("printer")}Imprimir PDF</button>',
    ),
    (
        '<button class="btn-primary" id="onboarding-create-demo" data-onclick-command="createDemoVault()">Crear ejemplo</button>',
        f'<button class="btn-primary" id="onboarding-create-demo" data-onclick-command="createDemoVault()">{icon("sparkles")}Crear ejemplo</button>',
    ),
    (
        '<button class="btn-secondary" id="onboarding-dismiss" data-onclick-command="dismissOnboarding()">Ahora no</button>',
        f'<button class="btn-secondary" id="onboarding-dismiss" data-onclick-command="dismissOnboarding()">{icon("close")}Ahora no</button>',
    ),
    (
        '<button class="btn-secondary" data-onclick-command="openOnboardingFromHelp()">Abrir ejemplo</button>',
        f'<button class="btn-secondary" data-onclick-command="openOnboardingFromHelp()">{icon("book-open")}Abrir ejemplo</button>',
    ),
]

for old, new in pairs:
    if old not in text:
        print("WARN missing:", old[:100].replace("\n", " "))
    else:
        text = text.replace(old, new, 1)

text = text.replace(
    '<button type="submit" class="btn-primary">Preguntar</button>',
    f'<button type="submit" class="btn-primary">{icon("send")}Preguntar</button>',
)

text = text.replace(
    '<div class="back-forward" aria-hidden="true"><span>‹</span><span>›</span></div>',
    f'<div class="back-forward" aria-hidden="true">{icon("chevron-left")}{icon("chevron-right")}</div>',
)
text = text.replace(
    '<div class="library-head"><h2>Biblioteca</h2><span aria-hidden="true">«</span></div>',
    f'<div class="library-head"><h2>Biblioteca</h2><span aria-hidden="true">{icon("panel-left-close")}</span></div>',
)

left = re.findall(
    r'<svg(?![^>]*class="ui-icon")[^>]*viewBox="0 0 24 24"[^>]*>[\s\S]*?</svg>',
    text,
)
print("remaining inline 24 svgs without ui-icon:", len(left))
for s in left[:15]:
    print(" ", s[:140].replace("\n", " "))

for g in ("◄", "⌕", "×", "&times;"):
    if g in text:
        print("BAD glyph", g)

html_path.write_text(text, encoding="utf-8")
print("ui-icon count", text.count('class="ui-icon"'))
print("symbols", text.count("<symbol id="))
print("done")
