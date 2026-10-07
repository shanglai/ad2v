// The web side of the polyglot fixture (P8.1): TypeScript, which no active extractor reads,
// so ad2v reports what it links as not_evaluable instead of guessing.

// ad2v: REQ-002
export function addToCart(cart: string[], item: string): string[] {
  return [...cart, item];
}
