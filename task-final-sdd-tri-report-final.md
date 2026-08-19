# Informe tri-versión — bloqueo final del SDD

Fecha: 2026-08-19  
Repositorio: `fuente`  
Tarea: revisión final amplia del SDD

## IA — estado técnico

Terra emitió `NEEDS_FIX/BLOCKED`. La revisión confirma que:

- el SDD ya describe el qué del proyecto y no el modo de actuación de los
  agentes;
- el diff publicado contiene sólo documentación e informes, sin cambios de
  código ni pruebas fuera de alcance;
- el ledger declara completas Tasks 1–10, P-01–P-08 y Q-01–Q-08;
- las evidencias registradas incluyen `1201 passed, 1 skipped, 1 warning` y
  `RESULT: READY`.

El bloqueo es una omisión normativa: la Definition of Done exige pruebas,
matriz focal, evidencia y registro en el SDD, pero no exige explícitamente el
dictamen final `APPROVED` de Terra. Eso permitiría cerrar una Q sin la decisión
del verificador.

Corrección requerida: añadir `Terra APPROVED` como criterio obligatorio y
dejar explícito que Sol sólo se consulta si Terra identifica una duda técnica
concreta. Sol no fue consultado porque Terra no lo solicitó.

## Tutor — explicación y decisión

La regla actual dice qué pruebas y documentos hacen falta, pero olvidó decir
que Terra tiene que aprobar el resultado. El proceso real sí lo exige, pero el
SDD no lo deja escrito.

Hay que añadir una frase a la Definition of Done: una Q sólo puede cerrarse
cuando Terra emite `APPROVED`; Sol no es una aprobación obligatoria y sólo
entra como asesor cuando Terra tiene una duda concreta.

Después hay que repetir el check documental y pedir a Terra una nueva revisión.

## Bro — resumen sencillo

El plan ya está limpio y no manda cómo trabajar. Pero falta una regla pequeña:
debe decir claramente que Terra tiene que dar el visto bueno antes de cerrar
una tarea.

No hace falta llamar a Sol. Hay que escribir esa regla, comprobar el documento
otra vez y dejar que Terra lo revise.

## Estado de parada

- Cambios de código: ninguno.
- SDD: publicado, pero pendiente de esta corrección normativa.
- Terra: `NEEDS_FIX/BLOCKED`; decisión final pendiente tras el fix.
- Sol: no consultado.
- Git: detenido; no se ha creado ningún nuevo commit, push ni PR.
