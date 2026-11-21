# Requests failure diagnostics — 21 November 2026

Workstream: [EVE-150](https://linear.app/eventquest/issue/EVE-150), under EVE-79.

## Why this change is needed

Southern Maltings source 6059's ordinary collector run at 10:36:29 UTC recorded
`source_network_error`, but its immediate Requests cause was logged only as
`OSError`. The observed Vercel request was
`nfbzk-1795257379735-1f530d096adb`; the fetch phase elapsed 9,648 ms. Those facts
do not identify a timeout, TLS failure, DNS failure or connection failure, and
they do not justify a transport change or retry.

Requests exceptions inherit from `OSError`, so the existing closed diagnostic
classifier lost the useful known class before emitting `error_type` or
`cause_type`. This patch adds six fixed Requests family labels before that
generic branch. Narrow subclasses precede their parents:

| Requests class | Fixed diagnostic label |
|---|---|
| `ConnectTimeout` | `RequestsConnectTimeout` |
| `ReadTimeout` | `RequestsReadTimeout` |
| `Timeout` | `RequestsTimeout` |
| `SSLError` | `RequestsSSLError` |
| `ConnectionError` | `RequestsConnectionError` |
| `RequestException` | `RequestsRequestException` |

The classifier never reads a dynamic class name, exception text, request,
response, URL or arbitrary nested exception chain. A Requests connection error
whose internal cause mentions DNS still receives the fixed connection label;
this patch does not infer a more specific cause. The existing separately
allowlisted urllib reason diagnostics remain unchanged.

## Scope and authorization

Root authorized an isolated observability follow-up after the registered-native
content core was reviewed and frozen. This patch changes only an import and
`_error_type` in `roomquest/category_worker.py`. A source-level comparison confirms
the other six function/class definitions are byte-identical to the pinned base.

`source_network_error`, source/worker disposition, fetch URL, robots policy,
timeouts, response handling, retries, source state, staging and finish callbacks
are unchanged. No source-specific behavior, new dependency, workflow dispatch,
production query, network request or data mutation is introduced.

Available `AGENTS.md` was read. The owner decision disables routine GitHub
diagnostics; no `ci:validate` label or test/audit workflow was dispatched. The
missing Bram-host guidance references were already recorded during this session;
the owner clarified that this workspace has no Bram Worklist surface. No host
approval, instruction edit or permission bypass is fabricated.

## Focused evidence

Original isolated base: `637136f98d7f112ac4dd3c1bf9dc6dbc6caadb1a`, independently
refreshed before this change. The original diagnostic review and red/green
evidence below preceded integration of the separate registered-native change.

The final expanded diagnostic tests on the untouched base fail 19 intended
Requests-label assertions with 44 passing. With this patch, the diagnostic and
existing transport suites pass **67 tests and 20 subtests**:

```bash
python -m pytest tests/test_category_network_diagnostics.py tests/test_preview_transport_errors.py -q
```

Tests exercise both direct exceptions and immediate causes, overlapping Requests
inheritance, secret-bearing request/response objects, custom subclass names,
unchanged builtin/urllib labels and the existing three-record/identity limits.
The real WordPress fetch normalization and worker callback path run with a
controlled `Session.get` failure: exactly one GET, existing `(3, 7)` connect/read
timeouts, redirects disabled, the same `source_network_error` receipt, no staged
events and the unchanged `failed` finish outcome. An initial fixture injected the
error above the transport normalizer and assumed the HTML lane's finish outcome;
the final fixture exercises the actual Requests boundary and preserves the
observed WordPress behavior instead.

No test opens a publisher or production connection. The patch cannot recover the
class of past logs or prove Southern Maltings will succeed. After a normal
reviewed release, only a subsequent ordinary authorized run can supply the more
precise receipt. Root owns merge/release and any supported Admin action.

## Integration after registered-native merge

On 21 November, root authorized reconciling the same diagnostic PR #413 onto
the actual collector main after PR #412 merged as
`7b5785288bb9ac35dd598ff90563bd8c0997b8c9`. A fresh branch/tree read confirmed that
exact main; all 14 native-content files and the unchanged `AGENTS.md` matched
the reviewed local blobs. The integrated diagnostic tree preserves those native
files, tests and documentation, with only the original separate Requests import
and six-label classifier delta added to `roomquest/category_worker.py`.

The diagnostic classifier body and diagnostic test file remain byte-identical
to the first reviewed PR #413 head. Removing just the import and replacing
`_error_type` with its main predecessor reproduces the complete main file
exactly; this also protects the native `_ERROR_CODES` additions outside function
bodies. The other six function/class definitions are individually unchanged.

The integrated focused suite passes **72 tests and 20 subtests**:

```bash
python -m pytest tests/test_category_network_diagnostics.py tests/test_preview_transport_errors.py tests/test_registered_native_content.py::test_native_failure_diagnostics_remain_closed_codes -q
```

The five additional cases exercise PR #412's native closed diagnostic codes in
the shared worker file. The earlier 67-test diagnostic/transport evidence remains
valid; the native 325-test suite was not redundantly rerun for this import and
classifier integration. `git diff --check` passes. No transport, native content,
media, timeout, retry or callback behavior was changed during reconciliation.

This integration is code-only. It does not assert that the diagnostic branch is
deployed or that Southern Maltings has recovered. No production action,
publisher fetch, workflow dispatch, source retry or merge was performed.
