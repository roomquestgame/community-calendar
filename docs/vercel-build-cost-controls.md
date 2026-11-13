# Collector build cost controls — November 5, 2026

Ben approved reducing unnecessary Vercel builds after the billing audit. `node scripts/vercel-ignore.mjs collector` keeps previews off and skips documentation, tests, excluded city outputs, Supabase and upstream UI changes in production. Runtime/parsers/dependencies/configuration and unknown inputs build conservatively. Comparison uses the last successful project/branch deployment, safely fetching a missing shallow object; missing history builds. `RQ_VERCEL_FORCE_BUILD=1` overrides selection. The existing one-minute geocoder/recovery cron and all provider workers are unchanged.

Five selector tests passed locally for the November 5 change. **Owner update, November 13, 2026:** provider validation is now manual-dispatch-only. Do not add `ci:validate` or require/run GitHub test suites as part of routine PRs or collector deployments; retain the tools for explicitly requested diagnostics. Production deployment receipts still belong in the PR body. The companion main-app PR documents opt-in web previews and transform-cache reuse. No runtime, provider, migration or credential changes.

