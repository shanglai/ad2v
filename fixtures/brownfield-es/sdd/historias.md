# Historias de usuario

## HU-001: Cargar un extracto

Como operador de tesorería, quiero cargar el extracto del día, para conciliarlo antes del cierre.

### Criterios de aceptación

1. El sistema deberá aceptar extractos en formato CSV y OFX.
2. Si el extracto ya fue cargado, entonces el sistema deberá rechazarlo.

## HU-002: Revisar pendientes

Como analista de conciliación, quiero ver los movimientos pendientes de una corrida, para resolverlos.

### Criterios de aceptación

- Dado una corrida con movimientos pendientes
- Cuando el analista abre la corrida
- Entonces ve los movimientos pendientes ordenados por monto

## HU-003: Aprobar una corrida

Como jefe de finanzas, quiero aprobar una corrida conciliada, para cerrar el día.

### Criterios de aceptación

1. Solo un usuario con rol de aprobador puede aprobar.
2. El sistema deberá registrar la fecha de aprobación.
