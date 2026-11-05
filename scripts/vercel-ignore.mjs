// Ignored Build Step: exit 0 skips; exit 1 builds. No dependencies or credentials.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

export function affectsBuild(path, profile = 'web') {
  if (path.startsWith('scripts/vercel-')) return !/\.test\.mjs$/.test(path);
  if (/^(docs|tests|e2e|supabase|\.github|\.claude)\//.test(path) || /\.md$/i.test(path)) return false;
  if (profile === 'collector') {
    if (/^(cities|reports|xmlui|website|node_modules)\//.test(path)) return false;
    return true; // Unknown inputs build rather than risk skipping a runtime change.
  }
  if (/^mobile\/(tests|ios|android)\//.test(path)) return false;
  if (/^mobile\/(eas\.json|AGENTS\.md|\.easignore)$/.test(path)) return false;
  if (/^mobile\/.*\.(ios|android|native)\.[cm]?[jt]sx?$/.test(path)) return false;
  if (/^(api|server|website|mobile)\//.test(path)) return true;
  if (path.startsWith('scripts/')) return false;
  return true;
}

export function buildDecision(env, paths, profile = 'web') {
  if (env.RQ_VERCEL_FORCE_BUILD === '1') return { build: true, reason: 'explicit force' };
  if (env.VERCEL_ENV === 'preview') {
    if (profile === 'collector') return { build: false, reason: 'collector previews disabled' };
    const optedIn = env.RQ_VERCEL_WEB_PREVIEW === '1'
      || (env.VERCEL_GIT_COMMIT_REF || '').startsWith('web-preview/')
      || /\[web-preview\]/i.test(env.VERCEL_GIT_COMMIT_MESSAGE || '');
    if (!optedIn) return { build: false, reason: 'web preview not requested' };
  }
  if (paths === null) return { build: true, reason: 'comparison unavailable; build safely' };
  const relevant = paths.some(path => affectsBuild(path, profile));
  return { build: relevant, reason: relevant ? 'deployment inputs changed' : 'no deployment inputs changed' };
}

export function changedPaths(env, cwd = process.cwd(), run = spawnSync) {
  const previous = env.VERCEL_GIT_PREVIOUS_SHA || '';
  // Compare with the last successful deployment, not HEAD^: skipped commits can
  // contain changes which must be included in the next real release.
  if (!/^[a-f0-9]{40}$/i.test(previous)) return null;
  const options = { cwd, encoding: 'utf8', timeout: 15000, maxBuffer: 4 * 1024 * 1024 };
  const root = run('git', ['rev-parse', '--show-toplevel'], options);
  if (root.status !== 0) return null;
  const gitOptions = { ...options, cwd: root.stdout.trim() };
  let exists = run('git', ['cat-file', '-e', previous + '^{commit}'], gitOptions);
  if (exists.status !== 0) {
    // Vercel's shallow checkout may omit the previous deployment. Fetch only
    // that validated object; never log Git output, which can contain URLs.
    const fetched = run('git', ['fetch', '--no-tags', '--depth=1', 'origin', previous], gitOptions);
    if (fetched.status !== 0) return null;
    exists = run('git', ['cat-file', '-e', previous + '^{commit}'], gitOptions);
    if (exists.status !== 0) return null;
  }
  const diff = run('git', ['diff', '--name-only', '--no-renames', '-z', previous, 'HEAD', '--'], gitOptions);
  return diff.status === 0 ? diff.stdout.split('\0').filter(Boolean) : null;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const profile = process.argv[2] || 'web';
  if (!['web', 'collector'].includes(profile)) process.exit(1);
  // Skip unrequested previews before any Git/network work.
  const early = buildDecision(process.env, null, profile);
  const decision = early.build && process.env.RQ_VERCEL_FORCE_BUILD !== '1'
    ? buildDecision(process.env, changedPaths(process.env), profile) : early;
  console.log(`Vercel ${decision.build ? 'BUILD' : 'SKIP'}: ${decision.reason}`);
  process.exit(decision.build ? 1 : 0);
}
