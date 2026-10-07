export function porcentaje(hechos: number, total: number): string {
  return total === 0 ? "0%" : `${Math.round((hechos / total) * 100)}%`;
}
