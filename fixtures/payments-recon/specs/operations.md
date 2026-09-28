# Operations notes

Finance-ops runs the reconciliation every night at 02:00 UTC. Operators must be able to export any
completed run as a CSV file, and the export has to include every matched pair and every unmatched
transaction together with its probable-cause label. Exports older than 90 days are deleted
automatically.

When the bank statement feed is more than 30 minutes late, the on-call engineer is paged. Nobody
may approve a run that still has unlabelled unmatched transactions.
