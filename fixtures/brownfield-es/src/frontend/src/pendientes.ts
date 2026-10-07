export interface Movimiento { id: number; monto: number; estado: string }

export function pendientes(movs: Movimiento[]): Movimiento[] {
  return movs.filter((m) => m.estado === "pendiente").sort((a, b) => b.monto - a.monto);
}
