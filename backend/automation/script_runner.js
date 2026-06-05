/**
 * CleanBrowser script-runtime wrapper.
 * Phase 7 phase 1 sandbox: same Node process, NO V8 isolate.
 * - Reads user script from CB_SCRIPT_PATH (TS or JS file).
 * - Provides `browser`, `page`, `log`, `vars` globals via VM context.
 * - Enforces hard timeout via setTimeout + process.exit.
 * - Production note: real multi-tenant SaaS needs Firecracker / gVisor isolation.
 */
const fs = require('fs');
const vm = require('vm');

const SCRIPT_PATH = process.env.CB_SCRIPT_PATH;
const CDP_URL = process.env.CB_CDP_URL;
const TIMEOUT_MS = parseInt(process.env.CB_TIMEOUT_MS || '60000', 10);
const LANGUAGE = process.env.CB_LANGUAGE || 'typescript';

const logLines = [];
const vars = {};

function emitResult(status, error) {
  const out = { status, log: logLines.join('\n'), vars, error: error || null };
  process.stdout.write('\n__CB_RESULT__' + JSON.stringify(out) + '__CB_RESULT__\n');
  process.exit(status === 'success' ? 0 : 1);
}

const hardTimeout = setTimeout(
  () => emitResult('failure', `Timeout after ${TIMEOUT_MS}ms`),
  TIMEOUT_MS,
);

async function run() {
  if (!SCRIPT_PATH || !fs.existsSync(SCRIPT_PATH)) {
    emitResult('failure', 'Missing script file');
    return;
  }
  let source = fs.readFileSync(SCRIPT_PATH, 'utf8');

  // TypeScript: strip type annotations using lightweight transpile.
  // Phase 7 phase 1: use sucrase if available, fallback raw (user can write JS).
  if (LANGUAGE === 'typescript') {
    try {
      const { transform } = require('sucrase');
      source = transform(source, { transforms: ['typescript'] }).code;
    } catch (e) {
      // sucrase not available — try raw, will work if no TS syntax
    }
  }

  let browser = null;
  let page = null;
  if (CDP_URL) {
    try {
      const { chromium } = require('playwright');
      browser = await chromium.connectOverCDP(CDP_URL);
      const ctx = browser.contexts()[0] || (await browser.newContext());
      page = ctx.pages()[0] || (await ctx.newPage());
    } catch (e) {
      logLines.push('CDP connect warning: ' + e.message);
    }
  }

  const sandbox = {
    browser,
    page,
    vars,
    log: (msg) => logLines.push(typeof msg === 'string' ? msg : JSON.stringify(msg)),
    console: { log: (...a) => logLines.push(a.join(' ')) },
    fetch: globalThis.fetch,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    Promise,
    JSON,
    Math,
    Date,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Error,
  };
  vm.createContext(sandbox);

  // Wrap user script in async IIFE to support top-level await
  const wrapped = `(async () => { ${source} \n})()`;
  try {
    await vm.runInContext(wrapped, sandbox, { timeout: TIMEOUT_MS });
    clearTimeout(hardTimeout);
    if (browser) await browser.close().catch(() => {});
    emitResult('success');
  } catch (e) {
    clearTimeout(hardTimeout);
    if (browser) await browser.close().catch(() => {});
    emitResult('failure', e.message || String(e));
  }
}

run().catch((e) => emitResult('failure', e.message || String(e)));
