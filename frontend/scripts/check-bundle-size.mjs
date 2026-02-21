import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const reportOnly = process.argv.includes('--report-only');
const distAssetsDir = path.resolve(process.cwd(), 'dist', 'assets');

const budgets = [
  { key: 'app-shell', test: (name) => /^index-.*\.js$/.test(name), maxKb: 120 },
  { key: 'pdf-viewer', test: (name) => /^pdf-viewer-.*\.js$/.test(name), maxKb: 250 },
  { key: 'pdfjs', test: (name) => /^pdfjs-.*\.js$/.test(name), maxKb: 180 },
  { key: 'single-chunk', test: (name) => /\.js$/.test(name), maxKb: 500 }
];

const toKb = (bytes) => bytes / 1024;
const formatKb = (bytes) => `${toKb(bytes).toFixed(2)} KB`;

const findBudget = (fileName) => budgets.filter((item) => item.test(fileName));

const main = () => {
  if (!fs.existsSync(distAssetsDir)) {
    console.error(`[bundle-check] Missing build output: ${distAssetsDir}`);
    process.exit(1);
  }

  const files = fs.readdirSync(distAssetsDir).filter((name) => name.endsWith('.js'));
  if (files.length === 0) {
    console.error('[bundle-check] No JS chunks found in dist/assets.');
    process.exit(1);
  }

  const rows = [];
  const failures = [];

  for (const fileName of files) {
    const fullPath = path.join(distAssetsDir, fileName);
    const source = fs.readFileSync(fullPath);
    const gzipBytes = zlib.gzipSync(source).length;
    const matchedBudgets = findBudget(fileName);

    for (const budget of matchedBudgets) {
      const maxBytes = budget.maxKb * 1024;
      const pass = gzipBytes <= maxBytes;
      rows.push({
        chunk: fileName,
        budget: budget.key,
        size: formatKb(gzipBytes),
        limit: `${budget.maxKb.toFixed(0)} KB`,
        status: pass ? 'PASS' : 'FAIL'
      });
      if (!pass) {
        failures.push({
          chunk: fileName,
          budget: budget.key,
          actual: formatKb(gzipBytes),
          limit: `${budget.maxKb.toFixed(0)} KB`
        });
      }
    }
  }

  console.table(rows);

  if (failures.length > 0) {
    console.error('[bundle-check] Budget violations:');
    for (const item of failures) {
      console.error(`- ${item.chunk} exceeds ${item.budget}: ${item.actual} > ${item.limit}`);
    }
    if (!reportOnly) {
      process.exit(1);
    }
  }

  console.log('[bundle-check] Completed.');
};

main();
