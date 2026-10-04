# Feature Specification: Card payments

**Feature Branch**: `001-payments`

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "Take card payments for an order."

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: template guidance stays out of the map.
-->

### User Story 1 - Pay for an order (Priority: P1)

A shopper pays for an order with a card and gets a receipt.

**Why this priority**: Without payment there is no sale.

**Independent Test**: Pay for one order and check the receipt.

**Acceptance Scenarios**:

1. **Given** an open order, **When** the shopper pays with a valid card, **Then** the order is marked paid
2. **Given** a declined card, **When** the shopper pays, **Then** the order stays open and the shopper sees why

---

### Edge Cases

- What happens when the card provider times out?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST charge the order total to the shopper's card.
- **FR-002**: System MUST record every charge attempt with its outcome.
- **FR-003**: System MUST retry a timed-out charge [NEEDS CLARIFICATION: how many times?]

### Key Entities

- **Charge**: one attempt to take money for an order.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 99% of valid charges complete in under 3 seconds.
