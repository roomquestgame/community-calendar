import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { affectsBuild, buildDecision, changedPaths } from './vercel-ignore.mjs';

const production = { VERCEL_ENV: 'production' };
test('skip tests, documentation and native-only inputs; retain all web runtime inputs', () => {
  for (const path of ['docs/handoff.md', 'supabase/migrations/a.sql', '.github/workflows/ios.yml',
    'mobile/tests/unit/a.ts', 'mobile/ios/Info.plist', 'mobile/android/build.gradle',
    'mobile/eas.json', 'mobile/src/lib/cache.native.ts', 'mobile/src/app/map.ios.tsx']) {
    assert.equal(affectsBuild(path), false, path);
  }
  for (const path of ['api/seo-event.js', 'server/event-seo.cjs', 'website/api/a.js',
    'mobile/src/app/index.tsx', 'mobile/src/lib/cache.web.ts', 'mobile/assets/icon.png',
    'mobile/metro.config.js', 'mobile/app.config.js', 'mobile/package-lock.json',
    'vercel.json', 'scripts/vercel-ignore.mjs', 'unknown-build-input']) {
    assert.equal(affectsBuild(path), true, path);
  }
});
test('web previews are opt-in; force and production remain available', () => {
  const preview = { VERCEL_ENV: 'preview' };
  assert.equal(buildDecision(preview, ['mobile/src/app/index.tsx']).build, false);
  for (const optIn of [{ RQ_VERCEL_WEB_PREVIEW: '1' }, { VERCEL_GIT_COMMIT_REF: 'web-preview/map' },
    { VERCEL_GIT_COMMIT_MESSAGE: 'Review map [web-preview]' }]) {
    assert.equal(buildDecision({ ...preview, ...optIn }, ['mobile/src/app/index.tsx']).build, true);
    assert.equal(buildDecision({ ...preview, ...optIn }, ['docs/a.md']).build, false);
  }
  assert.equal(buildDecision({ ...preview, RQ_VERCEL_FORCE_BUILD: '1' }, []).build, true);
  assert.equal(buildDecision(production, ['api/seo-event.js']).build, true);
  assert.equal(buildDecision(production, ['docs/a.md']).build, false);
  assert.equal(buildDecision(production, null).build, true);
});
test('collector skips previews and excluded docs/data; runtime and dependency changes build', () => {
  assert.equal(buildDecision({ VERCEL_ENV: 'preview' }, ['api/index.py'], 'collector').build, false);
  for (const path of ['docs/notes.md', 'cities/raleigh/events.ics', 'tests/test_worker.py', 'supabase/ddl/a.sql']) {
    assert.equal(affectsBuild(path, 'collector'), false, path);
  }
  for (const path of ['api/index.py', 'roomquest/event_media.py', 'scrapers/calendar.py',
    'pyproject.toml', 'requirements.txt', '.python-version', '.vercelignore', 'vercel.json']) {
    assert.equal(affectsBuild(path, 'collector'), true, path);
  }
});
test('real Git comparison retains earlier runtime changes across skipped commits and works from a subdirectory', () => {
  const dir = mkdtempSync(join(tmpdir(), 'rq-vercel-diff-'));
  const git = (...args) => execFileSync('git', args, { cwd: dir, encoding: 'utf8' }).trim();
  const commit = () => { git('add', '.'); git('-c', 'user.name=Test', '-c', 'user.email=test@local', 'commit', '-qm', 'fixture'); };
  try {
    git('init', '-q'); mkdirSync(join(dir, 'mobile')); mkdirSync(join(dir, 'docs'));
    writeFileSync(join(dir, 'mobile/app.ts'), 'before'); commit();
    const deployed = git('rev-parse', 'HEAD');
    writeFileSync(join(dir, 'mobile/app.ts'), 'after'); commit();
    writeFileSync(join(dir, 'docs/notes.md'), 'notes'); commit();
    const paths = changedPaths({ VERCEL_GIT_PREVIOUS_SHA: deployed }, join(dir, 'mobile'));
    assert.deepEqual(paths.sort(), ['docs/notes.md', 'mobile/app.ts']);
    assert.equal(buildDecision(production, paths).build, true);
    assert.deepEqual(changedPaths({ VERCEL_GIT_PREVIOUS_SHA: git('rev-parse', 'HEAD') }, dir), []);
    assert.equal(changedPaths({ VERCEL_GIT_PREVIOUS_SHA: '--unsafe' }, dir), null);
    const skipped = spawnSync(process.execPath, [new URL('./vercel-ignore.mjs', import.meta.url).pathname],
      { cwd: dir, env: { ...process.env, VERCEL_ENV: 'preview', RQ_VERCEL_WEB_PREVIEW: '', RQ_VERCEL_FORCE_BUILD: '' } });
    assert.equal(skipped.status, 0);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
test('missing shallow history fetches the validated SHA; Git errors cause a safe build', () => {
  const sha = 'a'.repeat(40); let fetched = false;
  const run = (_cmd, args) => {
    if (args[0] === 'rev-parse') return { status: 0, stdout: '/repo\n' };
    if (args[0] === 'cat-file') return { status: fetched ? 0 : 1 };
    if (args[0] === 'fetch') { assert.equal(args.at(-1), sha); fetched = true; return { status: 0 }; }
    return { status: 0, stdout: 'api/seo-event.js\0' };
  };
  assert.deepEqual(changedPaths({ VERCEL_GIT_PREVIOUS_SHA: sha }, '/repo', run), ['api/seo-event.js']);
  assert.equal(changedPaths({ VERCEL_GIT_PREVIOUS_SHA: sha }, '/repo', () => ({ status: 1 })), null);
});
