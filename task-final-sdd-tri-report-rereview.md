# Informe tri-versión — segundo bloqueo de la revisión SDD

Fecha: 2026-08-19  
Tarea: re-verificación de la neutralización del SDD

## IA — estado técnico

Terra emitió `NEEDS_FIX/BLOCKED`.

La primera objeción quedó resuelta: el SDD ya no contiene menciones a Luna,
Terra ni Sol. El diff mantiene estados, conteos, pruebas, gates y requisitos
técnicos; `git diff --check` está limpio.

La nueva objeción es estructural: el SDD todavía contiene un procedimiento de
ejecución amplio. Conserva pasos numerados, comandos `Run`, bloques `Expected`,
puntos humanos y checkpoints Git en Tasks 1–10 y Q-01–Q-08. Eso contradice la
sección que afirma que el procedimiento de trabajo queda fuera del SDD.

Corrección propuesta: dejar en el SDD sólo alcance, archivos/interfaces,
entregables, criterios de aceptación y evidencia histórica; mover la receta
operativa al ledger o a un informe separado.

## Tutor — explicación y decisión

Quitar los nombres de los agentes no basta. El documento sigue diciendo cómo
hay que trabajar: qué paso ejecutar primero, qué comando lanzar, cuándo hacer
un checkpoint y cuándo realizar una revisión humana.

Para que el SDD sea realmente el “qué”, hay que sacar esas instrucciones a un
documento operativo. El SDD debe conservar qué se construye y cómo se sabe que
está bien, pero no la receta de trabajo.

## Bro — resumen sencillo

El SDD ya no menciona a los agentes, pero todavía parece un manual de pasos.
Por eso Terra lo ha vuelto a parar.

Hay que dejar el plan con objetivos y resultados esperados, y mover los
comandos y pasos detallados a otro documento.

## Estado de parada

- Nombres de roles en el SDD: eliminados.
- Tests documentales: `23 passed`.
- Gate documental: `RESULT: READY`.
- Terra: `NEEDS_FIX/BLOCKED` por procedimiento operativo residual.
- Sol: no consultado.
- Git: detenido; no se ha creado ningún commit, push ni PR para esta revisión.
