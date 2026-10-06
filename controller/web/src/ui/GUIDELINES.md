# Dashboard UI guidelines

The dashboard uses the twenty-front stack. ADR 0006 records that choice.
New controls come from `controller/web/src/ui`. Use a component from that
folder when one already does the job.

## User-managed lists

A list of items the user runs and can remove always offers multi-select and
delete. Job Monitor is that list: every ledger row across the attached
projects. A later list of the same kind uses the same controls.

The control has four parts, used together:

1. A leading checkbox column. `SelectHead` and `SelectCell` live in
   `Table.tsx`. `SelectionCheckbox` lives in `Field.tsx`. The header checkbox
   selects every row in the current filter. A row checkbox selects that row.
   The column stays visible. A selected row sets
   `TRow` `$selected`.
2. `ActionBar` while the selection is not empty. It shows the count, Delete,
   and Clear selection. Delete and Backspace open the same confirmation when
   focus is outside a field. Escape clears the selection.
3. `Modal` before the delete runs. The copy names what the action removes and
   what it leaves in place.
4. One controller call for the whole selection, then `refresh()`.

`JobsMonitorPage` is the reference.

Cluster observations are a different list. The queue, other users, and
analytics show cluster state, and those pages stay without a delete control.

A workspace mutation that changes an execution stays on the reviewed-plan
path in the Runs pages. That path is a different action from removing a row
the user no longer wants in a list they manage.

## What delete does on Job Monitor

Delete removes the selected rows from Job Monitor.
The ledger retains scheduler receipts for execution recovery and job management.

A live scheduler job stays until a separate cancel. Remote files stay.
Execution history and its scheduler references remain available.

## Evaluation list removal

Evaluation lists use the same selection and confirmation controls.
Remove from list hides selected rows from GenAI views.
Source, results, indexes, frozen plans, artifacts, approvals, execution history, and scheduler receipts remain available.
Active executions must stop before removal.
Research tools retain access to the evidence.
