import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const project = resolve(import.meta.dirname, "../../..");
const artifacts = resolve(project, "artifacts");
await mkdir(artifacts, { recursive: true });
const browserPath = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const browser = await chromium.launch({ headless: true, executablePath: browserPath });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const errors = [];
const external = new Set();
page.on("pageerror", error => errors.push(error.message));
page.on("console", message => { if (message.type() === "error") errors.push(`${message.text()} @ ${message.location().url}`); });
page.on("response", response => { if (response.status() >= 400) errors.push(`HTTP ${response.status()} ${response.url()}`); });
page.on("request", request => {
  const url = new URL(request.url());
  if (!["127.0.0.1", "localhost"].includes(url.hostname)) external.add(request.url());
});

async function login(userId, password) {
  const role = userId === "sender" ? "sender" : userId.startsWith("REC-") ? "recipient" : userId;
  await page.getByRole("button", { name: `Sign in as ${role}` }).click();
  await page.locator("#login-user").fill(userId);
  await page.locator("#login-password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByText("One encrypted document.").waitFor();
}

async function logout() {
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await page.locator("#login-user").waitFor();
}

try {
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "SourceX", exact: true }).waitFor();
  for (const role of ["sender", "recipient", "investigator", "auditor"]) {
    if (await page.locator(`#${role}`).count() !== 1) throw new Error(`Missing ${role} landing section`);
  }
  for (const scene of ["journey", "sender", "recipient", "investigator", "auditor", "access"]) {
    await page.locator(`#${scene}`).scrollIntoViewIfNeeded();
    if (scene !== "access") await page.waitForFunction(id => document.querySelector(`#${id} [data-reveal]`)?.getAttribute("data-visible") === "true", scene);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  for (const image of ["iaf-tejas", "ins-vikrant", "indian-army", "indian-triservices"]) {
    const response = await page.request.get(`http://127.0.0.1:3000/imagery/${image}.webp`);
    if (response.status() !== 200) throw new Error(`Missing local ${image} image`);
  }
  await page.screenshot({ path: resolve(artifacts, "landing.png"), fullPage: true });
  await page.locator("#sender").getByRole("link", { name: /Next: Recipient/ }).click();
  await page.waitForFunction(() => location.hash === "#recipient");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(artifacts, "landing-mobile.png"), fullPage: true });
  const landingOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (landingOverflow) throw new Error("Landing page overflows the mobile viewport");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator("#login-user").waitFor();
  await login("sender", "Sender-2026!");
  await page.getByText("AIR-GAPPED MODE").first().waitFor();
  await page.screenshot({ path: resolve(artifacts, "dashboard.png"), fullPage: true });

  await page.getByRole("button", { name: "Documents" }).first().click();
  await page.locator("table tbody").getByText("Strategic_Exercise_Brief.pdf").waitFor();
  const synthetic = await page.request.get("http://127.0.0.1:8000/demo/sample-pdf");
  await page.locator("#pdf-upload").setInputFiles({ name: "Browser_Test_Brief.pdf", mimeType: "application/pdf", buffer: await synthetic.body() });
  await page.getByRole("button", { name: "Encrypt & add document" }).click();
  await page.getByText("Document encrypted once").waitFor();
  await page.getByRole("button", { name: "Create recipient envelopes" }).click();
  await page.getByText("3 ML-KEM envelopes created").waitFor();

  await logout();
  await login("REC-002", "Meera-2026!");
  await page.getByRole("button", { name: "Decrypt", exact: true }).first().click();
  await page.getByRole("button", { name: "Decrypt & commit event" }).click();
  await page.getByText("Recipient copy ready").waitFor();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download marked PDF" }).click();
  const download = await downloadEvent;
  const pdfPath = await download.path();

  await logout();
  await login("investigator", "Investigator-2026!");
  await page.getByRole("button", { name: "Forensics" }).first().click();
  await page.locator("#forensic-file").setInputFiles(pdfPath);
  await page.getByRole("button", { name: "Run forensic analysis" }).click();
  await page.getByText("VERIFIED MATCH").first().waitFor();
  await page.getByText("Lt. Commander Meera Singh").last().waitFor();
  await page.getByRole("button", { name: "Run digital transforms" }).click();
  await page.getByText("Text-only reconstruction (negative control)").waitFor();
  const negativeRow = page.getByRole("row").filter({ hasText: "Text-only reconstruction (negative control)" });
  await negativeRow.getByText("INCONCLUSIVE").waitFor();
  await page.screenshot({ path: resolve(artifacts, "forensics.png"), fullPage: true });

  await logout();
  await login("auditor", "Auditor-2026!");
  await page.getByRole("button", { name: "Ledger" }).first().click();
  await page.getByRole("button", { name: "Load blocks" }).click();
  await page.getByRole("button", { name: /BLOCK #000001/ }).click();
  await page.getByRole("button", { name: "Verify signature" }).click();
  await page.getByText("Ledger VALID · quorum 3/3").waitFor();
  await page.getByRole("button", { name: "Tamper validator-2" }).click();
  await page.getByText("DIVERGED").first().waitFor();
  await page.getByRole("button", { name: "Run independent check" }).click();
  await page.getByText("Matching replicas 2/3").waitFor();
  await page.getByRole("button", { name: "Restore validator-2" }).click();
  await page.getByRole("button", { name: "Verify entire chain" }).click();
  await page.getByRole("button", { name: "Run independent check" }).click();
  await page.getByText("Matching replicas 3/3").waitFor();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Ledger" }).first().waitFor();
  await page.screenshot({ path: resolve(artifacts, "mobile.png"), fullPage: true });

  const reducedPage = await browser.newPage({ reducedMotion: "reduce", viewport: { width: 390, height: 844 } });
  await reducedPage.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  const reduced = await reducedPage.evaluate(() => ({
    preference: matchMedia("(prefers-reduced-motion: reduce)").matches,
    visible: getComputedStyle(document.querySelector("#sender [data-reveal]")).opacity,
    heroAnimation: getComputedStyle(document.querySelector("#top"), "::before").animationName,
  }));
  await reducedPage.close();
  if (!reduced.preference || reduced.visible !== "1" || reduced.heroAnimation !== "none") throw new Error(`Reduced-motion landing failed: ${JSON.stringify(reduced)}`);

  if (errors.length) throw new Error(`Browser console errors: ${errors.join(" | ")}`);
  if (external.size) throw new Error(`Unexpected external requests: ${[...external].join(" | ")}`);
  console.log("PASS: dashboard, distribution, image-only recipient copy, forensic attribution, negative control and separate ledger tamper verification in Chrome");
  console.log("PASS: four local scenes, mobile layout, reduced motion, no browser console errors or external requests");
  console.log(`Screenshots: ${artifacts}`);
} finally {
  await browser.close();
}
