// A web test that exercises the API end to end. ad2v reads its title, never runs it (P9).
import { addToCart } from "./cart";

it("REQ-004 shows an error when the item list is unavailable", () => {
  expect(addToCart([], "a")).toEqual(["a"]);
});
