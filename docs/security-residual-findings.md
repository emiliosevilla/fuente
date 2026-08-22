# Hallazgos residuales de seguridad

Este registro es el punto de control para riesgos que permanezcan después de
una revisión. No afirma que la aplicación sea segura por la ausencia de filas:
todo hallazgo confirmado debe registrarse con evidencia, alcance, responsable
y decisión de corrección o aplazamiento.

El release gate bloquea únicamente las filas de severidad `P0` o `P1` cuyo
estado sea exactamente `open`. Las pruebas de seguridad siguen siendo
obligatorias aunque no haya un hallazgo abierto en este registro.

| ID | Severidad | Estado | Alcance | Evidencia y decisión |
| --- | --- | --- | --- | --- |
| SR-REGISTRY | N/A | no_open_p0_p1 | Registro inicial | No hay un hallazgo residual P0/P1 confirmado y abierto anotado en este registro. El gate y la suite de seguridad aportan la verificación de release. |

## Cómo registrar un hallazgo

1. Asignar un ID estable y describir el comportamiento reproducible, sin
   incluir secretos ni datos personales.
2. Indicar severidad, estado, componentes afectados, prueba o issue de
   seguimiento y la mitigación concreta.
3. Mantener `open` mientras un P0/P1 permita un impacto no aceptado. Cambiar
   el estado sólo con evidencia de la corrección y una prueba de regresión.
4. Para un riesgo aceptado o diferido, explicar el motivo, la fecha de revisión
   acordada y las salvaguardas. El estado no sustituye la evaluación humana.
