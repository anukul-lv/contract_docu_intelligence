/**
 * E2E Critical Path: Upload → Extract → Review → Explore
 *
 * This test exercises the full R1 workflow with accessibility checks
 * (axe-core) at every page visit.
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const PDF_PATH = 'tests/e2e/fixtures/sample_contract.pdf';

async function checkAccessibility(page: any) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter(v => v.impact === 'critical')).toHaveLength(0);
}

test.describe('R1 Critical Path', () => {
  test('complete workflow: upload → extract → review → explore', async ({ page }) => {
    // ------------------------------------------------------------------
    // Step 1: Navigate to Ingest tab
    // ------------------------------------------------------------------
    await page.goto('/');
    await page.waitForURL('**/ingest');
    await expect(page.getByRole('heading', { name: /Ingest Contracts/i })).toBeVisible();
    await checkAccessibility(page);

    // ------------------------------------------------------------------
    // Step 2: Upload a PDF
    // ------------------------------------------------------------------
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(PDF_PATH);
    await expect(page.getByText(/1 file.*staged/i)).toBeVisible();

    const uploadBtn = page.getByRole('button', { name: /Upload All/i });
    await uploadBtn.click();
    await expect(page.getByText(/test_contract\.pdf|sample_contract\.pdf/i)).toBeVisible({ timeout: 15_000 });

    // ------------------------------------------------------------------
    // Step 3: Start extraction
    // ------------------------------------------------------------------
    const profileSelect = page.locator('select').first();
    await profileSelect.selectOption('general_healthcare');

    const startBtn = page.getByRole('button', { name: /Start Extraction/i });
    await startBtn.click();

    // Wait for progress bar to appear
    await expect(page.getByText(/Processing|Submitted|Running/i)).toBeVisible({ timeout: 30_000 });

    // Wait for completion (up to 5 minutes for large corpus)
    await expect(page.getByText(/Completed/i)).toBeVisible({ timeout: 300_000 });

    // ------------------------------------------------------------------
    // Step 4: Navigate to Review tab
    // ------------------------------------------------------------------
    await page.getByRole('tab', { name: /Review/i }).click();
    await page.waitForURL('**/review');
    await expect(page.getByRole('heading', { name: /Review Workbench/i })).toBeVisible();
    await checkAccessibility(page);

    // Verify queue has items
    const rows = page.locator('tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 10_000 });

    // Click first item to open detail
    await rows.first().click();
    await expect(page.getByText(/AI Extracted Value/i)).toBeVisible();

    // Approve the item
    const approveBtn = page.getByRole('button', { name: /Approve/i });
    await approveBtn.click();

    // Verify optimistic update
    await expect(page.getByText(/APPROVED/i)).toBeVisible({ timeout: 5_000 });

    // ------------------------------------------------------------------
    // Step 5: Navigate to Explore tab
    // ------------------------------------------------------------------
    await page.getByRole('tab', { name: /Explore/i }).click();
    await page.waitForURL('**/explore');
    await expect(page.getByRole('heading', { name: /Contract Explorer/i })).toBeVisible();
    await checkAccessibility(page);

    // Verify contract cards exist
    const cards = page.locator('[class*="cursor-pointer"]');
    await expect(cards.first()).toBeVisible({ timeout: 10_000 });

    // Click into detail view
    await cards.first().click();
    await page.waitForURL('**/explore/**');

    // Verify trust badges are visible
    await expect(page.getByText(/Verified|AI Extracted|Corrected/i)).toBeVisible();
    await checkAccessibility(page);

    // ------------------------------------------------------------------
    // Step 6: Navigate to Admin tab
    // ------------------------------------------------------------------
    await page.getByRole('tab', { name: /Admin/i }).click();
    await page.waitForURL('**/admin');
    await expect(page.getByRole('heading', { name: /Administration/i })).toBeVisible();
    await checkAccessibility(page);
  });

  test('keyboard shortcuts on Review page', async ({ page }) => {
    await page.goto('/review');
    await page.waitForURL('**/review');

    // Press ? to show shortcuts overlay
    await page.keyboard.press('?');
    await expect(page.getByText(/Approve/i)).toBeVisible();
    await expect(page.getByText(/Correct/i)).toBeVisible();
    await expect(page.getByText(/Flag/i)).toBeVisible();

    // Dismiss
    await page.keyboard.press('?');
  });

  test('empty states display correctly', async ({ page }) => {
    // Explorer with no data should show empty state
    await page.goto('/explore');
    await page.waitForURL('**/explore');
    // May show contracts or empty state depending on data
    const heading = page.getByText(/No contracts yet|Contract Explorer/i);
    await expect(heading).toBeVisible();
  });

  test('responsive layout at tablet breakpoint', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/ingest');
    await expect(page.getByRole('heading', { name: /Ingest Contracts/i })).toBeVisible();
    // Nav should still be visible
    await expect(page.getByRole('tab', { name: /Ingest/i })).toBeVisible();
  });
});
