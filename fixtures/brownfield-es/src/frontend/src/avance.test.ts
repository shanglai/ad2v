import { porcentaje } from "./avance";

it("RF-008 muestra el avance de la corrida", () => {
  expect(porcentaje(5, 10)).toBe("50%");
});
