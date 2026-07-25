# AGENTS.md

## Project overview

Crabber is an asynchronous Bilibili live-room bot. Configuration is loaded from
JSON, and one `Crabber` instance is created for each configured room.

Each `Crabber` owns a worker thread and an asyncio event loop. It coordinates:

- Bilibili room information and danmaku events
- live-stream discovery and distribution
- scheduled jobs and background tasks
- optional components, services, and database adapters
- startup, room-state transitions, and explicit shutdown

The project targets Python 3.14 or newer.

## Architecture

- `src/crabber/main.py`: loads configuration, creates room instances, and owns
  process-level startup and shutdown.
- `src/crabber/crabber.py`: central runtime and room-state coordinator.
- `src/crabber/room_info.py`: mutable state for one live room.
- `src/crabber/live_stream.py` and `ffmpeg.py`: stream selection, distribution,
  and media-process management.
- `src/crabber/task_manager.py`: ownership and cancellation of background tasks.
- `src/crabber/components/`: event-driven bot features. A component normally
  exposes `default_events` and `get_handler(...)`, and may register lifecycle
  callbacks or scheduled jobs.
- `src/crabber/services/`: shared external integrations such as NapCat, ntfy,
  ASR, and LLM clients. Services must provide an async `close()` method.
- `src/crabber/database/`: database facade plus SQLite and Cloudflare D1
  adapters. The facade fans writes out to configured adapters.
- `test/`: unit/state-machine tests and several manually run integration scripts.

Components are registered before `Crabber.start()` dispatches lifecycle
callbacks. Keep this ordering intact so early room events cannot reach partially
initialized components.

Iris is deprecated and intentionally fails during initialization. Do not silently
enable it without addressing its ignored configuration and unbounded LLM context
growth.

## Async and lifecycle rules

- Keep room-bound asynchronous work on the owning `Crabber` event loop.
- Use `ctx.add_task(...)` for owned background work and `ctx.add_job(...)` for
  scheduled coroutine functions.
- Do not wrap scheduled coroutines in fire-and-forget callbacks; APScheduler must
  be able to enforce `max_instances` and coalescing.
- Protect room-state transitions with `RoomInfo.status_lock`.
- Avoid blocking sleeps or synchronous network/file work on an event loop.
  Use async APIs or `asyncio.to_thread(...)` where appropriate.
- Track every long-lived task, subprocess, session, and client, and close it
  during the explicit shutdown path.
- Preserve `CancelledError` when cancellation is part of task shutdown.
- Some integrations intentionally use best-effort delivery. Log failures at the
  boundary and preserve that behavior unless the task explicitly changes it.

## Coding style

- Prefer clear, typed Python over abstraction for its own sake.
- Follow the style already present in the file being edited.
- Use English for identifiers, comments, docstrings, developer-facing notes, and
  commit messages.
- Chinese or another target language is appropriate for text sent directly to
  users, danmaku, notification copy, and model prompts.
- Short comment fragments start with a lowercase letter.
- Preserve the capitalization of fixed abbreviations such as ASR, LLM, HTTP,
  URL, and Bilibili event names.
- A complete-sentence comment may use normal sentence capitalization and ending
  punctuation.

Examples:

```python
# update the cached room state
# ASR session cleanup
# This callback runs only after component registration completes.
```

### Line breaks and spacing

- Group imports as standard library, third-party packages, then local packages,
  with a blank line between groups.
- Keep two blank lines between top-level classes or functions.
- Use blank lines inside functions to separate meaningful stages such as
  validation, state updates, I/O, and callback dispatch.
- For a substantial function, a blank line after the signature before the first
  logical block is consistent with the existing style.
- When a signature, call, collection, or expression becomes long, wrap it across
  multiple lines with readable indentation. Prefer one argument per line and a
  trailing comma when using a fully multiline form.
- Keep the closing delimiter on its own line for fully multiline calls and data
  structures.
- A short one-line guard such as `if not value: return` is acceptable when it
  remains immediately understandable. Do not compress multi-step behavior.
- Avoid reformatting unrelated code solely to make it match a different style.

## Components and integrations

- Treat incoming Bilibili event payloads as untrusted and incomplete. Use safe
  lookups and reasonable defaults.
- Keep user-facing message construction separate from transport code where
  practical.
- A new service should subclass `BaseService`, define `service_name`, and close
  all owned resources in `close()`.
- A new database adapter should subclass `BaseAdapter`, serialize concurrent
  writes where required, and implement `close()`.
- Never expose values from `credential.json`, `config.json`, API tokens, cookies,
  or other local secrets. Put sanitized examples in the corresponding
  `*.example.json` files.

## Validation

Run checks relevant to the change. The main local checks are:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src test
.\.venv\Scripts\python.exe test\live_status_state_machine_test.py
.\.venv\Scripts\python.exe -m unittest discover -s test -p llm_test.py -v
```

Tests named `bili_*`, `napcat_test.py`, and `fun_asr_test.py` may require live
credentials or external services. Do not run them automatically unless the task
requires integration testing and the necessary access is available.

When commits are requested, use concise English commit messages and keep
unrelated fixes in separate commits. Do not push unless explicitly requested.
