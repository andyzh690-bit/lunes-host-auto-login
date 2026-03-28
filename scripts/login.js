const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const TARGET_URL = process.env.TARGET_URL || 'https://betadash.lunes.host/servers/73546';
const HEADLESS = parseBoolean(process.env.HEADLESS, true);
const RUN_TIMEOUT_MS = Number(process.env.RUN_TIMEOUT_MS || 120000);
const SUCCESS_URL_PATTERN = process.env.SUCCESS_URL_PATTERN || '/servers/73546';

const ROOT_DIR = path.resolve(__dirname, '..');
const ARTIFACTS_DIR = path.join(ROOT_DIR, 'artifacts');
const SCREENSHOTS_DIR = path.join(ARTIFACTS_DIR, 'screenshots');
const RESULTS_FILE = path.join(ARTIFACTS_DIR, 'login-results.json');

async function main () {
  ensureDir(ARTIFACTS_DIR);
  ensureDir(SCREENSHOTS_DIR);

  const accounts = getAccounts();
  if (!accounts.length) {
    throw new Error('No accounts configured. Set LOGIN_EMAIL and LOGIN_PASSWORD, or provide ACCOUNTS_JSON.');
  }

  const browser = await chromium.launch({
    headless: HEADLESS,
    proxy: buildProxyConfig(),
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox',
      '--disable-dev-shm-usage'
    ]
  });

  const results = [];

  try {
    for (let index = 0; index < accounts.length; index += 1) {
      const account = accounts[index];
      const result = await runForAccount(browser, account, index);
      results.push(result);
    }
  } finally {
    await browser.close();
  }

  fs.writeFileSync(RESULTS_FILE, JSON.stringify({
    targetUrl: TARGET_URL,
    generatedAt: new Date().toISOString(),
    results
  }, null, 2));

  await notifyTelegram(results);

  const failed = results.filter((item) => item.status !== 'success');
  if (failed.length) {
    process.exitCode = 1;
  }
}

async function runForAccount (browser, account, index) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1024 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
    locale: 'en-US'
  });

  const page = await context.newPage();
  page.setDefaultTimeout(RUN_TIMEOUT_MS);

  const safeName = sanitizeName(account.name || account.email || 'account-' + index);
  const startedAt = new Date().toISOString();
  const baseName = `${String(index + 1).padStart(2, '0')}-${safeName}`;

  try {
    await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: RUN_TIMEOUT_MS });
    await page.waitForLoadState('networkidle', { timeout: Math.min(RUN_TIMEOUT_MS, 30000) }).catch(() => {});

    if (isLoginPage(page.url())) {
      await fillLoginForm(page, account);
      await waitForCloudflare(page);
      await clickLogin(page);
    }

    await waitForLoginResult(page);

    const status = await detectSuccess(page);
    if (!status.success) {
      throw new Error(status.reason);
    }

    const successScreenshot = path.join(SCREENSHOTS_DIR, `${baseName}-success.png`);
    await page.screenshot({ path: successScreenshot, fullPage: true });

    const logoutResult = await logout(page);

    return {
      account: account.name || account.email,
      email: account.email,
      status: 'success',
      startedAt,
      finishedAt: new Date().toISOString(),
      url: page.url(),
      screenshot: toRelativePath(successScreenshot),
      logout: logoutResult
    };
  } catch (error) {
    const failureScreenshot = path.join(SCREENSHOTS_DIR, `${baseName}-failure.png`);
    await page.screenshot({ path: failureScreenshot, fullPage: true }).catch(() => {});

    return {
      account: account.name || account.email,
      email: account.email,
      status: 'failure',
      startedAt,
      finishedAt: new Date().toISOString(),
      url: page.url(),
      error: String(error && error.message ? error.message : error),
      screenshot: toRelativePath(failureScreenshot)
    };
  } finally {
    await context.close();
  }
}

async function fillLoginForm (page, account) {
  await page.locator('input[name="email"], input[type="email"]').first().fill(account.email);
  await page.locator('input[name="password"], input[type="password"]').first().fill(account.password);
}

async function waitForCloudflare (page) {
  const turnstileField = page.locator('textarea[name="cf-turnstile-response"], textarea[name="g-recaptcha-response"]');
  const iframe = page.locator('iframe[src*="turnstile"], iframe[title*="Widget"], iframe[src*="challenges.cloudflare.com"]');

  if (await iframe.count()) {
    await iframe.first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
  }

  const started = Date.now();
  while (Date.now() - started < RUN_TIMEOUT_MS) {
    if (await turnstileHasToken(turnstileField)) {
      return;
    }

    const challengePresent = await iframe.count();
    if (!challengePresent) {
      return;
    }

    await page.waitForTimeout(1500);
  }

  throw new Error('Cloudflare Turnstile was not solved before timeout. Use a stable proxy or rerun later.');
}

async function clickLogin (page) {
  const button = page.getByRole('button', { name: /continue to dashboard|sign in|login/i }).first();
  await button.click();
}

async function waitForLoginResult (page) {
  const started = Date.now();

  while (Date.now() - started < RUN_TIMEOUT_MS) {
    const success = await detectSuccess(page);
    if (success.success) {
      return;
    }

    const errorText = await getErrorText(page);
    if (errorText) {
      throw new Error(errorText);
    }

    if (!isLoginPage(page.url()) && page.url().includes(SUCCESS_URL_PATTERN)) {
      return;
    }

    await page.waitForTimeout(1500);
  }

  throw new Error('Timed out waiting for login success.');
}

async function detectSuccess (page) {
  const currentUrl = page.url();
  if (!isLoginPage(currentUrl) && currentUrl.includes(SUCCESS_URL_PATTERN)) {
    return { success: true };
  }

  const logoutLink = page.locator('a[href*="logout"], form[action*="logout"] button, button:has-text("Logout"), button:has-text("Sign out")').first();
  if (await logoutLink.count()) {
    return { success: true };
  }

  const dashboardHints = page.locator('text=/logout|sign out|dashboard|server/i').first();
  if (await dashboardHints.count()) {
    return { success: true };
  }

  return { success: false, reason: 'No authenticated dashboard markers found.' };
}

async function logout (page) {
  const selectors = [
    'a[href*="logout"]',
    'button:has-text("Logout")',
    'button:has-text("Sign out")',
    'summary:has-text("Logout")',
    'summary:has-text("Sign out")'
  ];

  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (await locator.count()) {
      await locator.click().catch(() => {});
      await page.waitForTimeout(1000);
      if (isLoginPage(page.url())) {
        return { attempted: true, success: true, url: page.url() };
      }
    }
  }

  const linkByText = page.getByRole('link', { name: /logout|sign out/i }).first();
  if (await linkByText.count()) {
    await linkByText.click().catch(() => {});
    await page.waitForTimeout(1000);
    return { attempted: true, success: isLoginPage(page.url()), url: page.url() };
  }

  return { attempted: false, success: false, url: page.url() };
}

async function getErrorText (page) {
  const candidates = [
    '.flash-message',
    '[role="alert"]',
    '.error',
    '.alert-danger',
    '.invalid-feedback'
  ];

  for (const selector of candidates) {
    const locator = page.locator(selector).first();
    if (await locator.count()) {
      const text = (await locator.textContent()) || '';
      const trimmed = text.trim();
      if (trimmed) {
        return trimmed;
      }
    }
  }

  return '';
}

async function turnstileHasToken (locator) {
  if (!await locator.count()) {
    return false;
  }

  const token = await locator.first().inputValue().catch(() => '');
  return Boolean(token && token.trim());
}

function getAccounts () {
  if (process.env.ACCOUNTS_JSON) {
    const parsed = JSON.parse(process.env.ACCOUNTS_JSON);
    if (!Array.isArray(parsed)) {
      throw new Error('ACCOUNTS_JSON must be a JSON array.');
    }

    return parsed.map(normalizeAccount);
  }

  if (process.env.LOGIN_EMAIL && process.env.LOGIN_PASSWORD) {
    return [normalizeAccount({
      email: process.env.LOGIN_EMAIL,
      password: process.env.LOGIN_PASSWORD,
      name: process.env.LOGIN_EMAIL
    })];
  }

  return [];
}

function normalizeAccount (account) {
  if (!account || !account.email || !account.password) {
    throw new Error('Each account must include email and password.');
  }

  return {
    email: String(account.email).trim(),
    password: String(account.password),
    name: account.name ? String(account.name).trim() : String(account.email).trim()
  };
}

function buildProxyConfig () {
  const explicitServer = process.env.LOGIN_PROXY_SERVER;
  const socks5Server = buildSocks5Server();
  const server = explicitServer || socks5Server;

  if (!server) {
    return undefined;
  }

  return {
    server,
    username: process.env.LOGIN_PROXY_USERNAME || process.env.S5_PROXY_USERNAME || undefined,
    password: process.env.LOGIN_PROXY_PASSWORD || process.env.S5_PROXY_PASSWORD || undefined,
    bypass: process.env.LOGIN_PROXY_BYPASS || undefined
  };
}

function buildSocks5Server () {
  const host = process.env.S5_PROXY_HOST;
  const port = process.env.S5_PROXY_PORT;

  if (!host || !port) {
    return '';
  }

  return `socks5://${host}:${port}`;
}

async function notifyTelegram (results) {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!botToken || !chatId) {
    return;
  }

  const total = results.length;
  const successCount = results.filter((item) => item.status === 'success').length;
  const failureCount = total - successCount;
  const lines = [
    'Lunes Host auto login result',
    `Target: ${TARGET_URL}`,
    `Success: ${successCount}/${total}`,
    `Failure: ${failureCount}`
  ];

  if (process.env.CI_RUN_URL) {
    lines.push(`Run: ${process.env.CI_RUN_URL}`);
  }

  for (const item of results) {
    lines.push(`- ${item.account}: ${item.status}${item.error ? ` (${item.error})` : ''}`);
  }

  await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      chat_id: chatId,
      text: lines.join('\n')
    })
  }).catch(() => {});

  for (const item of results) {
    if (!item.screenshot) {
      continue;
    }

    const absolutePath = path.join(ROOT_DIR, item.screenshot);
    if (!fs.existsSync(absolutePath)) {
      continue;
    }

    const form = new FormData();
    form.append('chat_id', chatId);
    form.append('caption', `${item.account}: ${item.status}`);
    form.append('photo', new Blob([fs.readFileSync(absolutePath)]), path.basename(absolutePath));

    await fetch(`https://api.telegram.org/bot${botToken}/sendPhoto`, {
      method: 'POST',
      body: form
    }).catch(() => {});
  }
}

function isLoginPage (url) {
  return /\/login(\?|$)/i.test(url);
}

function parseBoolean (value, defaultValue) {
  if (value === undefined || value === null || value === '') {
    return defaultValue;
  }

  return /^(1|true|yes|on)$/i.test(String(value));
}

function sanitizeName (value) {
  return String(value).replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'account';
}

function ensureDir (dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function toRelativePath (absolutePath) {
  return path.relative(ROOT_DIR, absolutePath).replace(/\\/g, '/');
}

main().catch((error) => {
  ensureDir(ARTIFACTS_DIR);
  fs.writeFileSync(RESULTS_FILE, JSON.stringify({
    targetUrl: TARGET_URL,
    generatedAt: new Date().toISOString(),
    fatalError: String(error && error.message ? error.message : error)
  }, null, 2));
  console.error(error);
  process.exit(1);
});
