# ADR-0006: Extra risk flag `slow_io_in_transaction`

- Status: accepted (P1). **Deviation (additive)** from the prompt's risk-flag list.
- Context: behavior nodes are emitted only when they carry a risk flag. None of the listed flags ever
  applies to a `transaction`, so transactions would appear only with `behavior.emit_all`. The
  classic transaction risk (holding a DB transaction open across a network, LLM or queue call) would
  go unreported.
- Decision: add `slow_io_in_transaction`. It is set when the transaction body touches an
  `external_service`, `llm_endpoint` or `queue`, directly or through resolved calls.
- Consequences: the risk-flag enum in the JSON Schema has 6 values. New flags are additive (format
  principle 7).
