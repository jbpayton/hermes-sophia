// Renders the explainer page frame by frame.
//   node render.js <page.html> <out.mp4>                 1920x1080, 30 fps, piped to ffmpeg
//   node render.js <page.html> <dir> --frames <fps> <scale>  PNG frames, for the README preview
// Needs Playwright (npm i playwright; npx playwright install chromium) and ffmpeg on PATH.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const [html, out, mode, fpsArg, scaleArg] = process.argv.slice(2);
const frames = mode === '--frames';
const FPS = frames ? Number(fpsArg) : 30, SCALE = frames ? Number(scaleArg) : 1.5;   // the stage is 1280x720

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: SCALE });
  await page.goto('file://' + path.resolve(html) + '?render');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  const n = Math.round(await page.evaluate(() => window.SOPHIA_DURATION) * FPS);
  const ff = frames ? null : spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', out], { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let i = 0; i < n; i++) {
    await page.evaluate(t => window.seek(t), i / FPS);
    const clip = { x: 0, y: 0, width: 1280, height: 720 };
    if (frames) {
      await page.screenshot({ path: path.join(out, String(i).padStart(4, '0') + '.png'), clip });
      continue;
    }
    const png = await page.screenshot({ type: 'png', clip });
    if (!ff.stdin.write(png)) await new Promise(r => ff.stdin.once('drain', r));
    if (i % 300 === 0) console.log(`frame ${i}/${n}`);
  }
  if (ff) {
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  }
  await browser.close();
})();
