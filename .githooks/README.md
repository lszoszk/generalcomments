# Git hooks

Tracked hooks live here so contributors get the same checks. Git stores
hooks in `.git/hooks/` (untracked), so you have to opt in once per clone:

```sh
git config core.hooksPath .githooks
```

That tells Git to run hooks from this directory instead of the default.
Verify with:

```sh
git config --get core.hooksPath        # → .githooks
ls -l .githooks                         # files must be executable
```

## Hooks

### `pre-push`

Runs the chromium Playwright suite before every push. Exits non-zero
if any test fails, blocking the push.

**Skip** for emergency hotfixes or doc-only changes:

```sh
UNHRDB_SKIP_TESTS=1 git push
```

The hook automatically skips when the push touches no files under
`docs/`, `tests/`, `playwright.config.ts`, or `package*.json`.

**Why a hook and not just CI?** GitHub Pages deploys directly from
`main/docs` — there's no workflow gate. A failing CI run still ships to
production. The hook is the only thing that can actually stop a broken
push from going live.
