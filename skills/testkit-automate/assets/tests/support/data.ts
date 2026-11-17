// Test data isolated per suite run, per project and per worker, so parallel runs never collide.
import type { TestInfo } from '@playwright/test';

export const RUN_TAG = process.env.TESTKIT_RUN_TAG ?? `e2e-${Date.now().toString(36)}`;

/** e.g. unique('note', testInfo) -> "e2e-lx3k9a-chromium-w0-note" */
export function unique(label: string, testInfo: TestInfo): string {
  return `${RUN_TAG}-${testInfo.project.name}-w${testInfo.workerIndex}-${label}`;
}

/** e.g. uniqueEmail('member', testInfo) -> "qa+e2e-lx3k9a-chromium-w0-member@example.test" */
export function uniqueEmail(role: string, testInfo: TestInfo, domain = 'example.test'): string {
  return `qa+${unique(role, testInfo)}@${domain}`.toLowerCase();
}
