# Requisitos del sistema de conciliación

Este documento lista los requisitos acordados con el equipo de finanzas.

## Conciliación

| ID | Título | Descripción | Prioridad | Tipo |
|----|--------|-------------|-----------|------|
| RF-001 | Iniciar conciliación | Cuando el operador envía un extracto, el sistema deberá iniciar una corrida de conciliación. | Alta | Funcional |
| RF-002 | | El sistema deberá emparejar cada movimiento bancario con un asiento del libro mayor. | Alta | Funcional |
| RF-003 | | Si un movimiento queda sin pareja, entonces el sistema deberá clasificarlo con una causa probable. | Media | Funcional |
| RF-004 | Formato de exportación | La exportación usa el separador `\|` y el formato `a|b` en las columnas | Baja | Funcional |
| **RF-005** | | Mientras el banco no responda, el sistema debe reintentar con espera
exponencial y un máximo de cinco intentos. | Media | Funcional |
| RF-X | | Fila con un identificador inválido | Baja | Funcional |

## Calidad

| Clave | Requisito | Tipo |
|-------|-----------|------|
| RNF-001 | El sistema deberá responder en menos de dos segundos. | No funcional |
| RNF-002 | Los datos deberán cifrarse en reposo. | No funcional |
| CAL-001 | El sistema deberá registrar cada acceso. | No funcional |
