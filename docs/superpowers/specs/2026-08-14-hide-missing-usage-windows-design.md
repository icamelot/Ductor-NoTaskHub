# Hide Missing Usage Windows Design

**Date:** 2026-08-14

This design supersedes the missing-individual-window rendering rule in
`2026-08-13-deepseek-usage-auth-sync-design.md`; all other requirements in that design remain in
force.

## Context

The provider usage clients can successfully return a partial plan-usage result. In particular,
Codex may provide its 7-day window without a short window. The current formatter renders every
missing individual window as an unlabeled `Unavailable` line, producing output such as:

```text
Plan: plus
Unavailable
7-day usage: 67% (...)
```

The request succeeded and the 7-day data is valid, so that line is ambiguous: it looks like a
provider-level failure rather than an absent optional window.

## Considered Approaches

1. Label each missing window explicitly, such as `Short window: unavailable`. This is precise but
   adds noise for a window the provider may not expose.
2. Hide every missing window unconditionally. This is compact, but a successful response with no
   windows would leave only the plan or an otherwise empty provider section.
3. Hide individual missing windows while rendering one provider-level `Unavailable` line when both
   windows are absent. This keeps partial results concise without making a no-window result silent.

Approach 3 is selected.

## Rendering Rules

For a successful `PlanUsage` result:

- render the plan when present;
- render the short-window line only when `short_window` is present;
- render the 7-day line only when `weekly_window` is present; and
- when both windows are absent, render exactly one localized `Unavailable` line.

For an unsuccessful `PlanUsage` result, preserve the existing bounded provider-level failure
message. Provider ordering, percentage formatting, reset-time conversion, localization, clients,
typed models, and transport routing remain unchanged.

## Implementation Boundary

The change belongs only in `ductor_bot/usage/formatting.py`. The existing
`usage.window_unavailable` localization key remains the fallback for the both-windows-absent case,
so locale files do not change.

## Tests

Update formatter tests to prove:

- a missing short window is omitted while a present 7-day window is rendered;
- a missing 7-day window is omitted while a present short window is rendered; and
- two missing windows produce exactly one `Unavailable` line.

The full test suite and static checks must remain clean before deployment.
