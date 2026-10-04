# Requirements Document

## Introduction

Operators export orders as CSV for the finance team. This spec mixes the two acceptance-criteria
styles Kiro has used (`WHEN … THEN … SHALL` and `WHEN …, THE … SHALL`).

## Glossary

- **Exporter**: the component that writes order rows to CSV.

## Requirements

### Requirement 1: Export orders as CSV

**User Story:** As an operator, I want to export a day's orders as CSV, so that finance can reconcile them.

#### Acceptance Criteria

1. WHEN an operator requests an export for a date THEN the Exporter SHALL write one CSV row per order of that date
2. WHEN the export contains no orders, THE Exporter SHALL write only the header row
3. IF the date is in the future THEN the Exporter SHALL reject the request with an error

### Requirement 2

**User Story:** As a finance analyst, I want amounts in cents, so that totals never round.

#### Acceptance Criteria

1. THE Exporter SHALL write every amount as an integer number of cents
2. WHILE an export is running, THE Exporter SHALL refuse a second export for the same date
