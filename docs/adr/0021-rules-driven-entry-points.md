# ADR-0021: Rules-driven entry points

- Status: accepted (P3)
- Context: P2's dispatch top-10 ranked by `reach`, but reach only counted HTTP/MCP/CLI-framework
  workflows. Scheduled jobs, task queues and scripts started nothing, so their risky loops looked
  unreachable. The prompt asks for main blocks, Celery tasks and beat, APScheduler, the `schedule`
  library and Click, with `attrs.trigger`.
- Decisions:
  1. **No new node kinds.** The closed enum stays: script entry points are `cli_command`
     (`trigger: main`), and task or schedule entry points are `event_consumer` (`trigger:
     celery_task`, `celery_beat`, `apscheduler`, `schedule`). The viewer distinguishes them by
     `attrs.trigger`.
  2. **Main blocks:** `if __name__ == "__main__":` (either operand order) gives
     `cli:<container>:__main__:<module path>`. The handler is the **module** (the block's calls are
     module-level events), and the port's span is the `if` block.
  3. **Recognizers live in the rules** (`ports.entry_points` in `rules/python.yaml`): decorator and
     call names per library, so overlays can extend them and `rules_hash` covers them.
  4. **Celery beat** resolves the `"task"` string of each schedule entry against the qualified
     names of decorated tasks. Unresolvable entries are skipped, not guessed.
  5. **Nested Click groups** are resolved to a fixpoint. A command's name is its **group path**
     without the root group (`cli:dispatch:plugins list`), because the bench found two nested groups
     that each define `list`. With bare names both mapped to one port id, and the file failed to
     write.
  6. **A port may bind several handlers** (the same route declared twice). The entry facts store
     the sorted handler list per port, and the port gets one workflow whose first call step holds
     all handlers as parallel targets. The workflow id stays one per port.
- Consequences: the payments-recon fixture gains one `cli_command` (the worker's main block).
  Dispatch gains 3 main-block ports and 38 Click ports with a trigger (REPORT §5).
