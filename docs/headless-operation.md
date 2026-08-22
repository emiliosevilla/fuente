# Operación sin interfaz

Fuente admite dos modos sin interfaz. Ambos usan el mismo Vault local y no
arrancan Tkinter ni PyWebView. Deben ejecutarse con una ruta de Vault explícita
en servidores, Docker o CI.

## Pasada puntual

`--flush` ejecuta una pasada determinista y termina. Es adecuado para un job
programado cuando no se necesita mantener servicios en memoria.

```bash
fuente --flush --vault /ruta/absoluta/Vault
```

La salida indica cuántos archivos se detectaron y procesaron. Antes de
programar una segunda pasada, esperar al fin del proceso anterior para evitar
dos escritores sobre el mismo Vault.

## Servicio continuo

`--headless` inicia el ciclo de vida de Fuente sin interfaz y permanece activo
hasta recibir su señal de parada. Es adecuado para un contenedor o servicio
supervisado por el sistema operativo.

```bash
fuente --headless --vault /ruta/absoluta/Vault
```

El supervisor debe enviar una señal de parada normal y esperar a que el
proceso termine. No terminarlo de forma forzada salvo que exista una
recuperación documentada, porque el cierre normal invoca la parada del ciclo de
vida.

## Límites operativos

- Sólo ejecutar una instancia escritora por Vault.
- El Vault elegido se crea si aún no existe; comprobar la ruta antes de lanzar
  el proceso para no crear un Vault en una ubicación errónea.
- Los convertidores, OCR, audio, Ollama y Chroma son opcionales y se activan
  según las dependencias locales y la política de ejecución.
- La sincronización con una carpeta montada es local. Fuente no gestiona
  credenciales, OAuth ni permisos de SharePoint.

Para validar una instalación antes de ponerla bajo supervisión, usar primero
una pasada `--flush` sobre un Vault de prueba y ejecutar el release gate desde
el repositorio.
