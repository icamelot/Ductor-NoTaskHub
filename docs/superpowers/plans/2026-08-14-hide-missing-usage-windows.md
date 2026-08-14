# Hide Missing Usage Windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide absent individual Claude/Codex usage windows while retaining one localized `Unavailable` line when a successful provider response contains no windows.

**Architecture:** Keep provider clients and typed models unchanged. Adjust only the provider-neutral formatter so `_plan_lines()` appends present windows conditionally and uses the existing localized fallback only when both windows are absent.

**Tech Stack:** Python 3.14, frozen dataclass usage models, pytest, Ruff, mypy, uv tool deployment, systemd user service.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-14-hide-missing-usage-windows-design.md`.
- Preserve the DeepSeek, Claude Code, Codex section order and all provider-level bounded failures.
- Do not change clients, typed models, localization files, transport routing, snapshot behavior, or Docker behavior.
- A present window retains its current label, percentage normalization, reset conversion, and timezone formatting.
- A missing individual window produces no output line; two missing windows produce exactly one localized `Unavailable` line.
- Preserve all user-owned untracked files in the main checkout.

## File Structure

- Modify `ductor_bot/usage/formatting.py`: conditionally render plan-usage windows.
- Modify `tests/usage/test_service.py`: lock the three missing-window cases through the public `format_usage()` API.

---

### Task 1: Hide Missing Individual Usage Windows

**Files:**
- Modify: `ductor_bot/usage/formatting.py:42-59`
- Test: `tests/usage/test_service.py:285-345`

**Interfaces:**
- Consumes: `PlanUsage.short_window: UsageWindow | None`, `PlanUsage.weekly_window: UsageWindow | None`, and `_window(window, *, label, timezone) -> str`.
- Produces: unchanged `_plan_lines(usage: PlanUsage, *, timezone: ZoneInfo) -> list[str]` with the approved omission semantics.

- [ ] **Step 1: Create an isolated worktree and verify the baseline**

Run:

```bash
git status --short --branch
git check-ignore -q .worktrees
git worktree add /home/zqxu/ductor/.worktrees/hide-missing-usage-windows \
  -b fix/hide-missing-usage-windows main
cd /home/zqxu/ductor/.worktrees/hide-missing-usage-windows
/home/zqxu/ductor/.venv/bin/pytest -q
```

Expected: the worktree starts from the design/plan commits, tracked status is clean, and the baseline reports `4070 passed, 3 skipped`.

- [ ] **Step 2: Write the failing public formatter tests**

In `test_format_usage_renders_three_ordered_complete_sections()`, replace the old missing-window expectation with:

```python
assert "**Codex**\nPlan: plus\n7-day usage: 100%" in rendered
assert "Unavailable\n7-day usage: 100%" not in rendered
```

Add this helper and the two remaining cases after that test:

```python
def _report_with_codex(codex: PlanUsage) -> UsageReport:
    return UsageReport(
        deepseek=DeepseekUsage(ok=False, failure=UsageFailure.UNAVAILABLE),
        claude=PlanUsage(
            provider="claude", ok=False, failure=UsageFailure.UNAVAILABLE
        ),
        codex=codex,
    )


def test_format_usage_hides_missing_weekly_window() -> None:
    rendered = format_usage(
        _report_with_codex(
            PlanUsage(
                provider="codex",
                ok=True,
                plan="plus",
                short_window=UsageWindow(Decimal(25)),
            )
        ),
        timezone=ZoneInfo("UTC"),
    )

    codex_section = rendered.split("**Codex**\n", maxsplit=1)[1]
    assert codex_section == "Plan: plus\nShort window: 25%"


def test_format_usage_renders_one_unavailable_when_both_windows_are_missing() -> None:
    rendered = format_usage(
        _report_with_codex(PlanUsage(provider="codex", ok=True, plan="plus")),
        timezone=ZoneInfo("UTC"),
    )

    codex_section = rendered.split("**Codex**\n", maxsplit=1)[1]
    assert codex_section == "Plan: plus\nUnavailable"
```

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/usage/test_service.py::test_format_usage_renders_three_ordered_complete_sections \
  tests/usage/test_service.py::test_format_usage_hides_missing_weekly_window \
  tests/usage/test_service.py::test_format_usage_renders_one_unavailable_when_both_windows_are_missing \
  -q
```

Expected: all three tests fail because the current formatter inserts `Unavailable` for every missing window.

- [ ] **Step 4: Implement the minimal conditional rendering**

Replace the successful-window portion of `_plan_lines()` in `ductor_bot/usage/formatting.py` with:

```python
    short_label = "usage.five_hour" if usage.provider == "claude" else "usage.short_window"
    if usage.short_window is not None:
        lines.append(_window(usage.short_window, label=short_label, timezone=timezone))
    if usage.weekly_window is not None:
        lines.append(
            _window(usage.weekly_window, label="usage.weekly", timezone=timezone)
        )
    if usage.short_window is None and usage.weekly_window is None:
        lines.append(t("usage.window_unavailable"))
    return lines
```

Do not modify `_window()`, because it still owns percentage/reset formatting and its existing contract remains compatible.

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_service.py -q
/home/zqxu/ductor/.venv/bin/pytest tests/usage -q
```

Expected: both commands pass; partial provider results omit only the missing line and both-missing results retain one fallback.

- [ ] **Step 6: Run full verification**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest -q
/home/zqxu/ductor/.venv/bin/ruff check .
/home/zqxu/ductor/.venv/bin/ruff format --check .
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
git diff --check
```

Expected: `4072 passed, 3 skipped`; Ruff, formatting, mypy, and whitespace checks exit zero.

- [ ] **Step 7: Commit the behavior change**

```bash
git add ductor_bot/usage/formatting.py tests/usage/test_service.py
git commit -m "fix(usage): hide missing plan windows"
```

Expected: one focused commit containing only formatter code and regression tests.

---

### Task 2: Review, Integrate, and Deploy

**Files:**
- Verify: `ductor_bot/usage/formatting.py`
- Verify: `tests/usage/test_service.py`

**Interfaces:**
- Consumes: the reviewed Task 1 commit and the uv tool installation at `/home/zqxu/.local/share/uv/tools/ductor`.
- Produces: `origin/main` and the running `ductor.service` using the reviewed formatter.

- [ ] **Step 1: Request a read-only code review**

Review the range from the Task 1 base SHA to its head SHA against the approved design. Resolve every Critical or Important finding, then rerun Task 1 Step 6.

- [ ] **Step 2: Fast-forward main and verify the merged result**

From `/home/zqxu/ductor`:

```bash
git merge --ff-only fix/hide-missing-usage-windows
/home/zqxu/ductor/.venv/bin/pytest -q
/home/zqxu/ductor/.venv/bin/ruff check .
/home/zqxu/ductor/.venv/bin/ruff format --check .
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
```

Expected: the fast-forward succeeds and the same full verification remains clean on `main`.

- [ ] **Step 3: Push and reinstall the actual runtime**

```bash
git push origin main
uv tool install --force --from /home/zqxu/ductor ductor
cmp \
  /home/zqxu/ductor/ductor_bot/usage/formatting.py \
  /home/zqxu/.local/share/uv/tools/ductor/lib/python3.14/site-packages/ductor_bot/usage/formatting.py
```

Expected: `origin/main` advances, the tool reinstall succeeds, and `cmp` exits zero.

- [ ] **Step 4: Fully stop and restart Ductor**

```bash
ductor service stop
# Wait until ~/.ductor/bot.pid is absent and logs contain "PID lock released".
ductor service start
```

Expected: the old PID fully exits before start; a new PID file is created and the main Telegram bot logs `Run polling for bot`.

- [ ] **Step 5: Verify the live command output**

Send `/usage` to the Telegram main bot.

Expected Codex section when only the weekly window is returned:

```text
Codex
Plan: plus
7-day usage: 67% (resets ...)
```

No standalone `Unavailable` line appears.

- [ ] **Step 6: Clean up the owned worktree**

After merge and deployment verification:

```bash
git worktree remove /home/zqxu/ductor/.worktrees/hide-missing-usage-windows
git worktree prune
git branch -d fix/hide-missing-usage-windows
git status --short --branch
```

Expected: the temporary worktree/branch are removed; `main` matches `origin/main`; protected user-owned untracked files remain unchanged.
