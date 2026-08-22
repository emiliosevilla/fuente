# Release gate de Fuente

El release gate es el control fail-closed previo a una publicación. No modifica
el Vault de producción: ejecuta pruebas, revisa el árbol de trabajo, valida la
documentación y recorre un Vault temporal offline.

## Ejecución

Instala el extra de pruebas y ejecútalo desde la raíz del repositorio:

```bash
pip install -e ".[test]"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/release_gate.py
```

El resultado válido para publicar es `RESULT: READY`. Cualquier otro resultado
es un bloqueo: se corrige la causa y se vuelve a ejecutar el gate completo.

## Controles que cubre

- Las suites unitarias, de integración, seguridad, contrato, operación sin
  interfaz, migración, sincronización y el propio gate.
- La honestidad del README y la presencia de los documentos operativos.
- Los hallazgos residuales de seguridad: una fila `P0` o `P1` con estado
  `open` bloquea la publicación.
- La higiene de artefactos de build y la limpieza del árbol de trabajo.
- La concordancia entre el código fuente y
  `docs/evidence/current-sdd.json`.
- Un ciclo temporal offline de migración, ingesta, aprobación, recuperación,
  exportación y rollback.

## Orden de publicación

1. Ejecutar el gate con el árbol limpio y conservar su salida.
2. Si se modifica código, pruebas o configuración después del gate, repetirlo.
3. Publicar mediante la cascada Git aprobada del repositorio.
4. Tras el merge, medir de nuevo rama, referencias, árbol y gate para registrar
   el estado realmente publicado.

Los documentos nuevos o la evidencia regenerada hacen que el árbol deje de
estar limpio hasta el commit. En ese caso se puede validar el resto de
controles de forma focal y se debe repetir el gate completo tras crear el
commit; nunca se interpreta esa condición como un `RESULT: READY` anticipado.
