import type { Page } from "@playwright/test";

export type BrowserDiagnostics = {
  consoleErrors: string[];
  ignoredConsoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  failedResponses: string[];
  nonLocalRequests: string[];
};

const localHosts = new Set(["127.0.0.1", "localhost"]);

export function collectBrowserDiagnostics(page: Page): BrowserDiagnostics {
  const diagnostics: BrowserDiagnostics = {
    consoleErrors: [],
    ignoredConsoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    failedResponses: [],
    nonLocalRequests: [],
  };

  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location().url || "unknown location";
      const detail = `${message.text()} (${location})`;
      const isMissingFavicon =
        location === `${page.url().replace(/\/$/, "")}/favicon.ico` ||
        location === "http://127.0.0.1:3000/favicon.ico";

      if (isMissingFavicon && message.text().includes("status of 404")) {
        diagnostics.ignoredConsoleErrors.push(detail);
      } else {
        diagnostics.consoleErrors.push(detail);
      }
    }
  });

  page.on("pageerror", (error) => {
    diagnostics.pageErrors.push(error.stack || error.message);
  });

  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "unknown failure";
    diagnostics.failedRequests.push(
      `${request.method()} ${request.url()} (${reason})`,
    );
  });

  page.on("response", (response) => {
    if (response.status() >= 400) {
      diagnostics.failedResponses.push(
        `${response.status()} ${response.request().method()} ${response.url()}`,
      );
    }
  });

  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      ["http:", "https:", "ws:", "wss:"].includes(url.protocol) &&
      !localHosts.has(url.hostname)
    ) {
      diagnostics.nonLocalRequests.push(`${request.method()} ${request.url()}`);
    }
  });

  return diagnostics;
}

export function formatDiagnostics(diagnostics: BrowserDiagnostics): string {
  return JSON.stringify(diagnostics, null, 2);
}
