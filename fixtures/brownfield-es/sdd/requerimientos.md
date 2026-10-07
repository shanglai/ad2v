# Requerimientos: plataforma de conciliación bancaria

Documento de requerimientos acordado con Finanzas y Operaciones (versión 3).

## Requerimientos funcionales

| ID | Título | Descripción | Componente | Prioridad |
|----|--------|-------------|------------|-----------|
| RF-001 | Iniciar conciliación | Cuando el operador carga un extracto bancario, el sistema deberá iniciar una corrida de conciliación. | Backend | Alta |
| RF-002 | | El sistema deberá emparejar cada movimiento del extracto con un asiento del libro mayor. | Backend | Alta |
| RF-003 | | Si un movimiento queda sin pareja, entonces el sistema deberá marcarlo como pendiente. | Backend | Alta |
| RF-004 | | El sistema deberá permitir consultar una corrida por su identificador. | Backend | Media |
| RF-005 | | El sistema deberá exportar una corrida aprobada en formato CSV. | Backend | Media |
| RF-006 | | Mientras el banco no responda, el sistema debe reintentar la descarga del extracto. | Backend | Baja |
| RF-007 | | La pantalla de conciliación muestra los movimientos pendientes en rojo. | Frontend | Media |
| RF-008 | | El sistema deberá mostrar el avance de la corrida en la pantalla principal. | Frontend | Media |
| RF-009 | | El sistema deberá permitir descargar el CSV desde la pantalla de la corrida. | Frontend | Baja |
| RF-010 | | El sistema deberá registrar quién aprobó cada corrida. | Backend | Alta |

## Requerimientos no funcionales

| Clave | Requisito | Tipo |
|-------|-----------|------|
| RNF-001 | El sistema deberá conciliar 100.000 movimientos en menos de cinco minutos. | No funcional |
| RNF-002 | Los extractos deberán cifrarse en reposo. | No funcional |
| RNF-003 | El sistema deberá estar disponible el 99,5% del horario hábil. | No funcional |
| RNF-004 | Las corridas deberán conservarse durante diez años. | No funcional |
