@CMP-001
Feature: Statement reconciliation
  Operators reconcile bank statements against the ledger.

  Background:
    Given the ledger database is available

  @REQ-001 @REQ-002
  Scenario: Start a reconciliation run
    Given bank statements for accounts "A1" and "A2"
    When the operator starts a reconciliation run
    Then each transaction is matched against the ledger
    And the run is recorded

  @REQ-004
  Scenario: Classify unmatched transactions
    Given a completed reconciliation run with unmatched transactions
    When the operator lists unmatched transactions
    Then each unmatched transaction has a probable-cause label

  @REQ-007
  Scenario: Approve a reconciliation run
    Given a completed reconciliation run
    When a reviewer approves the run
    Then the run status becomes "approved"
