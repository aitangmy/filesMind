import { expect, test } from '@playwright/test';

function buildConfigPayload() {
  return {
    schema_version: 2,
    active_profile_id: 'provider_deepseek',
    profiles: [
      {
        id: 'provider_deepseek',
        name: 'DeepSeek',
        provider: 'deepseek',
        base_url: 'https://api.deepseek.com',
        model: 'deepseek-chat',
        api_key: '',
        has_api_key: false,
        account_type: 'free',
        manual_models: [],
      },
    ],
    parser: {
      parser_backend: 'docling',
      hybrid_noise_threshold: 0.2,
      hybrid_docling_skip_score: 70,
      hybrid_switch_min_delta: 2,
      hybrid_marker_min_length: 200,
      marker_prefer_api: false,
      task_timeout_seconds: 600,
    },
    advanced: {
      engine_concurrency: 5,
      engine_temperature: 0.3,
      engine_max_tokens: 8192,
    },
  };
}

test('unified settings tabs switch and advanced autosave posts updated values', async ({ page }) => {
  const savedPayloads = [];

  await page.route('**/api/history', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  await page.route('**/api/system/hardware', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ device_type: 'gpu' }) });
  });

  await page.route('**/api/system/features', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        FEATURE_VIRTUAL_PDF: false,
        FEATURE_SIDECAR_ANCHOR: false,
      }),
    });
  });

  await page.route('**/api/config', async (route) => {
    const req = route.request();
    if (req.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildConfigPayload()),
      });
      return;
    }
    if (req.method() === 'POST') {
      savedPayloads.push(JSON.parse(req.postData() || '{}'));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          message: '配置已保存',
          active_profile_id: 'provider_deepseek',
        }),
      });
      return;
    }
    await route.fulfill({ status: 405, body: '' });
  });

  await page.goto('/');

  await page.getByTestId('settings-open-btn').click();
  await expect(page.getByTestId('settings-modal')).toBeVisible();
  await expect(page.getByTestId('settings-model-panel')).toBeVisible();

  await page.getByTestId('settings-tab-parser').click();
  await expect(page.getByTestId('settings-parser-panel')).toBeVisible();

  await page.getByTestId('settings-tab-advanced').click();
  await expect(page.getByTestId('settings-advanced-panel')).toBeVisible();

  await page.getByTestId('advanced-concurrency').evaluate((el) => {
    el.value = '7';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.getByTestId('advanced-temperature').evaluate((el) => {
    el.value = '0.65';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.getByTestId('advanced-max-tokens').evaluate((el) => {
    el.value = '11000';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });

  await expect
    .poll(() => savedPayloads.length, { timeout: 5_000 })
    .toBeGreaterThan(0);

  const latest = savedPayloads[savedPayloads.length - 1];
  expect(latest.advanced.engine_concurrency).toBe(7);
  expect(latest.advanced.engine_temperature).toBe(0.65);
  expect(latest.advanced.engine_max_tokens).toBe(11000);
});
