import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  collectBrowserDiagnostics,
  formatDiagnostics,
} from "./support/diagnostics";

type StreamEvent = {
  type: string;
  stage?: string;
  answer?: string;
  sources?: string[];
  metadata?: {
    telemetry?: Record<string, unknown>;
    [key: string]: unknown;
  };
  conversation?: { id?: string };
};

const runAcceptance = process.env.RUN_RAG_GOAL2_ACCEPTANCE === "1";
const evidenceDir = process.env.RAG_GOAL2_EVIDENCE_DIR;
const pdfPath = path.resolve(
  process.cwd(),
  "..",
  "..",
  "composite_goldset_pdfs",
  "doh-16-381.pdf",
);

function parseJsonLines(raw: string): StreamEvent[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as StreamEvent);
}

async function sendAndCapture(page: Page, question: string) {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/ask/stream",
  );
  await page.getByLabel("پیام").fill(question);
  await page.getByTitle("ارسال").click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const events = parseJsonLines(await response.text());
  const final = [...events].reverse().find((event) => event.type === "final");
  expect(final, `No final event for ${question}`).toBeDefined();
  const visiblePrefix = String(final?.answer ?? "")
    .replace(/\[S\d+\]/g, "")
    .trim()
    .slice(0, 36);
  await expect(page.getByTestId("message-assistant").last()).toContainText(
    visiblePrefix,
    { timeout: 20_000 },
  );
  return { events, final: final as StreamEvent };
}

function telemetryOf(result: Awaited<ReturnType<typeof sendAndCapture>>) {
  return result.final.metadata?.telemetry ?? {};
}

test.describe("Goal 2 real production UI acceptance", () => {
  test.skip(!runAcceptance, "Set RUN_RAG_GOAL2_ACCEPTANCE=1 for paid acceptance");

  test("summary, clarification, and table QA stay in one conversation", async ({
    page,
  }, testInfo: TestInfo) => {
    test.setTimeout(300_000);
    expect(evidenceDir, "RAG_GOAL2_EVIDENCE_DIR is required").toBeTruthy();
    await mkdir(evidenceDir!, { recursive: true });
    const diagnostics = collectBrowserDiagnostics(page);
    const sanitizedTrace: Record<string, unknown>[] = [];
    const recordResult = async (
      scenario: string,
      result: Awaited<ReturnType<typeof sendAndCapture>>,
    ) => {
      sanitizedTrace.push({
        scenario,
        event_types: result.events.map((event) => event.type),
        streaming_stages: result.events
          .filter((event) => event.type === "trace")
          .map((event) => event.stage),
        answer: result.final.answer,
        sources: result.final.sources,
        telemetry: telemetryOf(result),
      });
      await writeFile(
        path.join(evidenceDir!, "sanitized-trace.json"),
        JSON.stringify(sanitizedTrace, null, 2),
        "utf8",
      );
    };

    try {
      await page.goto("/", { waitUntil: "domcontentloaded" });
      expect(new URL(page.url()).pathname).not.toBe("/login");
      await page.waitForLoadState("networkidle");
      const newConversation = page.getByRole("button", {
        name: "گفتگوی جدید",
        exact: true,
      });
      await expect(newConversation).toBeVisible();
      await newConversation.click();
      await expect(page.getByText("از کجا شروع کنیم؟")).toBeVisible();

      await page.getByTitle("افزودن منبع یا ابزار").click();
      await page.getByRole("button", { name: "انتخاب منابع", exact: true }).click();
      await expect(page.getByTestId("source-modal")).toBeVisible();

      const uploadResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === "/api/gallery/upload",
      );
      await page.getByTestId("upload-input").setInputFiles(pdfPath);
      const uploadResponse = await uploadResponsePromise;
      expect(uploadResponse.ok()).toBe(true);
      const uploadBody = await uploadResponse.json();
      const assetId = String(uploadBody.created?.[0]?.id ?? "");
      expect(assetId).not.toBe("");
      await writeFile(
        path.join(evidenceDir!, "uploaded-asset.json"),
        JSON.stringify({ asset_id: assetId, filename: "doh-16-381.pdf" }, null, 2),
        "utf8",
      );
      sanitizedTrace.push({
        upload: {
          asset_id: assetId,
          filename: "doh-16-381.pdf",
          status: "uploaded",
        },
      });

      await expect
        .poll(
          async () => {
            const response = await page.context().request.get(
              "http://127.0.0.1:5000/api/gallery/assets",
            );
            const body = await response.json();
            return body.assets?.find((asset: { id: string }) => asset.id === assetId)
              ?.status;
          },
          { timeout: 90_000, intervals: [500, 1000, 2000] },
        )
        .toBe("scanned");

      await page.getByTestId("source-modal").getByRole("button").first().click();
      await page.getByTitle("افزودن منبع یا ابزار").click();
      await page.getByRole("button", { name: "انتخاب منابع", exact: true }).click();
      const assetRow = page
        .getByTestId("source-modal")
        .locator(`label[data-asset-id="${assetId}"]`);
      await expect(assetRow).toContainText("آماده");
      await assetRow.getByRole("checkbox").check();
      await page.getByTestId("source-modal").getByRole("button").first().click();
      await expect(page.getByText(/منابع:\s*۱/)).toBeVisible();

      const summary = await sendAndCapture(
        page,
        "یک خلاصه مفهومی و جامع از کل مقاله بده و همه بخش‌های اصلی را پوشش بده.",
      );
      await recordResult("summary", summary);
      expect(summary.final.answer).toContain("عنوان سند:");
      expect(summary.final.answer).toContain("بازیافت آب");
      expect(summary.final.answer).toContain("تاپسیس");
      expect(summary.final.answer).toContain("نتیجه‌گیری:");
      expect(summary.final.sources?.length).toBeGreaterThan(0);
      expect(summary.events.some((event) => event.stage === "agent_plan")).toBe(false);
      expect(JSON.stringify(summary.events)).not.toContain("برنامه پاسخ انتخاب شد");
      const summaryTelemetry = telemetryOf(summary);
      expect(summaryTelemetry.selected_route).toBe("direct_whole_document");
      expect(summaryTelemetry.retrieval_calls).toBe(0);
      expect(summaryTelemetry.embedding_calls).toBe(0);
      expect(summaryTelemetry.rewrite_calls).toBe(0);
      expect(summaryTelemetry.reranker_calls).toBe(0);
      await page.getByTestId("message-assistant").last().scrollIntoViewIfNeeded();
      await page.screenshot({
        fullPage: true,
        path: path.join(evidenceDir!, "01-summary.png"),
      });

      const clarification = await sendAndCapture(page, "یعنی چی؟");
      await recordResult("clarification", clarification);
      expect(clarification.final.answer).toMatch(/بازیافت آب|بیمارستان/);
      expect(clarification.final.answer).not.toContain(
        "اطلاعات کافی برای پاسخ وجود ندارد",
      );
      const clarificationTelemetry = telemetryOf(clarification);
      expect(clarificationTelemetry.selected_route).toBe("conversation_only");
      expect(clarificationTelemetry.conversation_id).toBe(
        summaryTelemetry.conversation_id,
      );
      expect(clarificationTelemetry.selected_asset_id).toBe(assetId);
      for (const key of [
        "retrieval_calls",
        "embedding_calls",
        "rewrite_calls",
        "reranker_calls",
      ]) {
        expect(clarificationTelemetry[key]).toBe(0);
      }
      await page.getByTestId("message-assistant").last().scrollIntoViewIfNeeded();
      await page.screenshot({
        fullPage: true,
        path: path.join(evidenceDir!, "02-clarification.png"),
      });

      const table = await sendAndCapture(
        page,
        "طبق جدول ۴، کدام راهکار رتبهٔ اول را کسب کرد و شاخص نزدیکی به ایده‌آل آن چه بود؟",
      );
      await recordResult("table", table);
      expect(table.final.answer).toContain("بازیافت پساب دیالیز");
      expect(table.final.answer).toMatch(/۰٫۸۷|0\.87/);
      expect(table.final.sources?.some((source) => /صفحه 9|صفحه ۹/.test(source))).toBe(
        true,
      );
      const tableTelemetry = telemetryOf(table);
      expect(tableTelemetry.selected_route).toBe("table_or_structured_document");
      expect(tableTelemetry.conversation_id).toBe(summaryTelemetry.conversation_id);
      expect(tableTelemetry.selected_asset_id).toBe(assetId);
      expect(tableTelemetry.retrieval_calls).toBe(1);
      expect(tableTelemetry.embedding_calls).toBe(0);
      expect(tableTelemetry.rewrite_calls).toBe(0);
      expect(tableTelemetry.reranker_calls).toBe(0);
      await page.getByTestId("message-assistant").last().scrollIntoViewIfNeeded();
      await page.screenshot({
        fullPage: true,
        path: path.join(evidenceDir!, "03-table.png"),
      });

      sanitizedTrace.push({
        upload: {
          asset_id: assetId,
          filename: "doh-16-381.pdf",
          status: "scanned",
        },
      });
    } finally {
      await writeFile(
        path.join(evidenceDir!, "sanitized-trace.json"),
        JSON.stringify(sanitizedTrace, null, 2),
        "utf8",
      );
      await writeFile(
        path.join(evidenceDir!, "browser-diagnostics.json"),
        JSON.stringify(diagnostics, null, 2),
        "utf8",
      );
      await testInfo.attach("goal2-browser-diagnostics", {
        body: Buffer.from(JSON.stringify(diagnostics, null, 2)),
        contentType: "application/json",
      });
    }

    const details = formatDiagnostics(diagnostics);
    expect(diagnostics.consoleErrors, details).toEqual([]);
    expect(diagnostics.pageErrors, details).toEqual([]);
    expect(diagnostics.failedRequests, details).toEqual([]);
    expect(diagnostics.failedResponses, details).toEqual([]);
    expect(diagnostics.nonLocalRequests, details).toEqual([]);
  });
});

test("capture the already accepted Goal 2 conversation", async ({ page }) => {
  test.skip(
    process.env.RAG_GOAL2_CAPTURE_EXISTING !== "1",
    "Set RAG_GOAL2_CAPTURE_EXISTING=1 for evidence-only capture",
  );
  expect(evidenceDir, "RAG_GOAL2_EVIDENCE_DIR is required").toBeTruthy();
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");
  const assistantMessages = page.getByTestId("message-assistant");
  await expect(assistantMessages).toHaveCount(3);
  await expect(assistantMessages.nth(0)).toContainText("عنوان سند:");
  await expect(assistantMessages.nth(1)).toContainText(/بازیافت آب|بیمارستان/);
  await expect(assistantMessages.nth(2)).toContainText("بازیافت پساب دیالیز");

  for (const [index, filename] of [
    [0, "01-summary.png"],
    [1, "02-clarification.png"],
    [2, "03-table.png"],
  ] as const) {
    await assistantMessages.nth(index).evaluate((element) =>
      element.scrollIntoView({ behavior: "instant", block: "start" }),
    );
    await page.screenshot({
      fullPage: false,
      path: path.join(evidenceDir!, filename),
    });
  }
});
