# Terra — dictamen final del SDD

## VERDICT: NEEDS_FIX/BLOCKED

El SDD no puede declararse completo todavía. No consulté a Sol: no hay una
duda técnica que requiera su asesoramiento; el bloqueo es una omisión concreta
en la regla de cierre.

## Evidencia revisada

- El paquete `7c5c912..78b2e47` contiene sólo el plan SDD y dos informes
  documentales (143 inserciones, 37 eliminaciones). No introduce código ni
  pruebas fuera de alcance.
- El plan ya expresa el qué del proyecto (registro canónico, derivados,
  migración y consola) y elimina las instrucciones de ejecución para agentes.
  Sus criterios de entrega se limitan a entregables, evidencia y gate.
- El ledger reconciliado declara completas las Tasks 1–10; P-01–P-08 y
  Q-01–Q-08 están cerrados. Las casillas históricas no son por sí solas el
  estado actual, conforme a la regla de lectura del propio plan.
- Gates observados en el ledger, no reejecutados en esta revisión: matriz
  relacionada P-08 `172 passed`; suite completa `1201 passed, 1 skipped,
  1 warning`; release gate `RESULT: READY`, incluyendo `source_tree_clean` y
  `documentation_freshness`. El warning se atribuye a telemetría externa de
  ChromaDB. Las Q-04–Q-08 también registran sus matrices focales y aprobación
  de Terra.

## Objeción bloqueante

La Definition of Done actual exige pruebas de aceptación, matriz focal,
evidencia y registro en el SDD, pero no exige que Terra apruebe el cierre. Por
tanto una Q podría marcarse `COMPLETE` sin la decisión final requerida por el
protocolo vigente. Aunque los cierres publicados sí documentan dictámenes
Terra, la política escrita queda incompleta y permite cierres futuros no
gobernados.

## Corrección necesaria

Modificar la Definition of Done para exigir el dictamen `APPROVED` de Terra y
dejar explícito que Sol sólo se consulta si Terra identifica una duda técnica
concreta; no debe ser un requisito universal. Después, repetir el check
documental y someter esa corrección a la decisión final de Terra.
