import { expect, test } from "@playwright/test";

import {
  collectBrowserDiagnostics,
  formatDiagnostics,
} from "./support/diagnostics";

const frontendUrl = "http://127.0.0.1:3000";
const backendHealthUrl = "http://127.0.0.1:5000/api/health";

test("local frontend and backend smoke test", async ({ page, request }, testInfo) => {
  const diagnostics = collectBrowserDiagnostics(page);
  let frontendStatus: number | null = null;
  let backendStatus: number | null = null;

  try {
    const frontendResponse = await page.goto(frontendUrl, {
      waitUntil: "domcontentloaded",
    });
    frontendStatus = frontendResponse?.status() ?? null;

    expect(frontendResponse, `No response received for ${frontendUrl}`).not.toBeNull();
    expect(
      frontendResponse?.ok(),
      `${frontendUrl} returned HTTP ${frontendStatus}`,
    ).toBe(true);
    await expect(page.locator("body")).toBeVisible();
    expect(new URL(page.url()).hostname).toBe("127.0.0.1");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toMatch(
      /Application error|Internal Server Error|Unhandled Runtime Error/i,
    );

    const healthResponse = await request.get(backendHealthUrl);
    backendStatus = healthResponse.status();
    expect(
      healthResponse.ok(),
      `${backendHealthUrl} returned HTTP ${backendStatus}`,
    ).toBe(true);
    expect(new URL(healthResponse.url()).hostname).toBe("127.0.0.1");
    expect(await healthResponse.json()).toMatchObject({ status: "ok" });

    const details = formatDiagnostics(diagnostics);
    expect(diagnostics.consoleErrors, `Console errors:\n${details}`).toEqual([]);
    expect(diagnostics.pageErrors, `Uncaught page errors:\n${details}`).toEqual([]);
    expect(diagnostics.failedRequests, `Failed requests:\n${details}`).toEqual([]);
    expect(diagnostics.failedResponses, `HTTP error responses:\n${details}`).toEqual([]);
    expect(diagnostics.nonLocalRequests, `Non-local requests:\n${details}`).toEqual([]);
  } finally {
    await testInfo.attach("smoke-diagnostics", {
      body: Buffer.from(
        JSON.stringify(
          {
            frontend: { url: page.url(), status: frontendStatus },
            backend: { url: backendHealthUrl, status: backendStatus },
            ...diagnostics,
          },
          null,
          2,
        ),
      ),
      contentType: "application/json",
    });
  }
});
