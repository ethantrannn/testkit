// Signs in once per role and saves the session (storageState) for every spec that needs it.
// Adapt the steps to the product's real sign-in screen (same locators as the sign-in case).
import { test as setup, expect } from '@playwright/test';
import { authFile, credentials } from './support/accounts';

const ROLES = ['member']; // roles used by specs through test.use({ storageState: authFile('<role>') })

for (const role of ROLES) {
  setup(`authenticate as ${role}`, async ({ page }) => {
    const { email, password } = credentials(role);
    await page.goto('/login');
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/dashboard/);
    await page.context().storageState({ path: authFile(role) });
  });
}
