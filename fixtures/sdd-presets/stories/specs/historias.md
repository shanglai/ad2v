# Historias de usuario: conciliación

## HU-001: Exportar una conciliación

Como analista de finanzas, quiero exportar una conciliación aprobada, para cargarla en el ERP.

### Criterios de aceptación

1. El archivo exportado deberá incluir cada pareja conciliada.
2. Cuando la conciliación no está aprobada, el sistema deberá rechazar la exportación.

## HU-002: Revisar movimientos sin pareja

Como **revisor**, quiero ver los movimientos sin pareja de una corrida, para decidir su causa.

**Criterios de aceptación:**

- Dado una corrida con movimientos sin pareja
- Cuando el revisor abre la corrida
- Entonces ve la lista de movimientos sin pareja
- Y cada movimiento muestra su causa probable
- Dado una corrida sin movimientos pendientes
- Cuando el revisor abre la corrida
- Entonces ve el mensaje "todo conciliado"

## Otras historias

- **HU-003**: Como un operador del turno noche, quiero reintentar una corrida fallida para no esperar al día siguiente.
