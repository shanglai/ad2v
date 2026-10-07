# language: es
Característica: Conciliación de un extracto
  Como operador de tesorería
  quiero conciliar el extracto del día
  para cerrar las cuentas a tiempo

  Antecedentes:
    Dado un libro mayor con asientos del día

  @RF-001 @RF-002
  Escenario: Conciliar un extracto completo
    Dado un extracto con tres movimientos
    Cuando el operador inicia la conciliación
    Entonces la corrida empareja los tres movimientos

  @RF-003
  Escenario: Un movimiento sin pareja queda pendiente
    Dado un extracto con un movimiento desconocido
    Cuando el operador inicia la conciliación
    Entonces el movimiento queda pendiente
    Y la corrida no se puede aprobar

  @RF-008
  Esquema del escenario: El avance se muestra en pantalla
    Dado una corrida con <total> movimientos
    Cuando se han procesado <hechos>
    Entonces la pantalla muestra <porcentaje>

    Ejemplos:
      | total | hechos | porcentaje |
      | 10    | 5      | 50%        |
