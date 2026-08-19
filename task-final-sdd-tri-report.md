# Informe tri-versión — bloqueo de cierre SDD

Fecha: 2026-08-19  
Repositorio: `fuente`  
Rama medida: `dev`

## IA — diagnóstico técnico

Terra ha emitido `NEEDS_FIX/BLOCKED`. La reconciliación de las casillas
internas de Q-04, Q-05 y Q-08 es correcta; las casillas antiguas abiertas de
`progress.md` pertenecen a un corte histórico y no representan tareas
pendientes actuales.

El bloqueo real está en `docs/superpowers/plans/2026-08-14-fuente-execution-sdd.md`:
su `Definition of Done de las tareas Q` exige que Sol emita `APPROVED` antes
de marcar una Q como `COMPLETE`, pero los cierres actuales de Q-04, Q-05,
Q-06, Q-07 y Q-08 registran aprobación de Terra sin consulta a Sol cuando
Terra no encontró problemas. Esto contradice el protocolo `/tandem` vigente.

No se ha aplicado Git. El estado medido antes de este informe tenía sólo el
plan versionado modificado por la reconciliación y el informe de Terra nuevo.

## Tutor — explicación sencilla

Hay dos documentos que dicen cosas incompatibles:

1. La regla antigua dice: “para cerrar una Q hace falta que Sol la apruebe”.
2. La regla de trabajo confirmada después dice: “Terra verifica y decide; Sol
   sólo aconseja si Terra encuentra un problema”.

Terra ha hecho bien en parar. No podemos afirmar que el SDD está cerrado
cuando sus propias reglas se contradicen. Tampoco debemos pedir ahora a Sol
aprobaciones retroactivas sólo para satisfacer una regla antigua.

La corrección razonable es actualizar la Definition of Done y los briefs para
dejar escrito que Terra puede cerrar una Q si aprueba y no hay un hallazgo que
justifique consultar a Sol. Después habría que repetir el check documental y
volver a pedir la aprobación de Terra.

## Bro — resumen directo

Terra ha encontrado una contradicción en el papel:

- el SDD dice que siempre hace falta Sol;
- el modo tándem dice que Sol sólo entra si Terra detecta un problema.

Por eso no publico ni marco el SDD como cerrado. No llamé a Sol porque no lo
pidió Terra. Hay que decidir si corregimos esa regla antigua para que coincida
con el modo de trabajo actual, o si se quiere convocar a Sol para revisar esas
Q de forma retroactiva.

## Estado y decisión solicitada

- Implementación: sin cambios pendientes derivados de este bloqueo.
- Reconciliación SDD: preparada, pero no aprobada para publicar.
- Tests documentales previos: `23 passed`; `documentation_freshness`:
  `RESULT: READY`.
- Git: detenido, sin commit, push ni PR.
- Sol: no convocado, conforme a `/tandem`.

Quedo detenido a la espera de la decisión del usuario sobre cómo reconciliar
la regla de aprobación.
