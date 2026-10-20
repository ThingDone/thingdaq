# Repository Agent Instructions

- Commit cohesive completed work at checkpoints and push it to `origin/main`
  while working; do not leave verified work only in the local worktree.
- Keep unrelated or pre-existing changes out of those commits unless the user
  explicitly asks to include them.
- Run validation appropriate to the changed surface before committing, and
  never force-push or bypass a failing required gate.
- Route rig HTTP requests through `firmware/tools/run_input_isolation.py`:
  every HTTP 500–599 is transient, retried every 30 seconds until 10 minutes
  of continuous 5xx for that request. Never halt Auto Run or mark a task
  blocked on one 5xx. Queued jobs are normal on this shared rig; wait without
  charging queue residence to execution timeouts or the HTTP retry budget.
- Before retrying `/start`, reconcile its saved submission tag against the rig
  journal (or follow its saved job ID with `/status`). Never assume a 5xx means
  nothing was accepted. Resume retained jobs with the runner's `--resume`;
  do not create another job or execute archived raw-evidence clients.
