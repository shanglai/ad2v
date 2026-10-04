# Feature Specification: Refunds

**Feature Branch**: `002-refunds`

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Refund a paid order (Priority: P1)

Support refunds a paid order in full.

**Acceptance Scenarios**:

1. **Given** a paid order, **When** support requests a full refund, **Then** the shopper's card is credited

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST refund at most the amount that was charged.
- **FR-002**: System MUST record every refund with the support agent who requested it.
