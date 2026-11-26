// Screenshot the actual HTML report generated from scanner outputs.
const { chromium } = require('../../code/frontend/node_modules/@playwright/test');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
async function captureReport() {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1160, height: 1100 }, deviceScaleFactor: 1 });
    const folder = path.resolve(__dirname, '../../docs/software/quality_evidence');
    await page.goto(pathToFileURL(path.join(folder, 'report.html')).href);
    await page.evaluate(() => document.fonts.ready);
    for (const phase of ['before', 'after', 'comparison']) {
      await page.locator('#' + phase).screenshot({ path: path.join(folder, phase + '.png') });
    }
  } finally { await browser.close(); }
}

captureReport().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
