"""Build the one-minute explainer: a self-contained page, and optionally the video.

    python scripts/explainer/build.py            # writes build/explainer/sophia-explainer.html
    python scripts/explainer/build.py --video    # also renders docs/video/ (needs Node with Playwright, ffmpeg, Pillow)

The page embeds two dashboard screenshots, so rebuild after those change. Every example in it is from Almanac's
synthetic "Silas" life, quoted word for word from the demo store (scripts/dashboard_demo_store.py)."""
import base64
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
OUT = REPO / "build" / "explainer"
VIDEO = REPO / "docs" / "video"


def page() -> pathlib.Path:
    s = (HERE / "explainer.html").read_text()
    img = REPO / "docs" / "img" / "dashboard"
    for key, name in (("__GRAPH__", "graph.webp"), ("__RECALL__", "recall.webp")):
        s = s.replace(key, "data:image/webp;base64," + base64.b64encode((img / name).read_bytes()).decode())
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "sophia-explainer.html"
    out.write_text(s)
    return out


def video(html: pathlib.Path) -> None:
    VIDEO.mkdir(parents=True, exist_ok=True)
    master = OUT / "master.mp4"
    subprocess.run(["node", str(HERE / "render.js"), str(html), str(master)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(master), "-c:v", "libx264", "-preset", "slow", "-crf", "24",
                    "-tune", "animation", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(VIDEO / "sophia-explainer.mp4")], check=True)
    preview(html)


def preview(html: pathlib.Path, fps: int = 8) -> None:
    """The README's animated WebP, from frames rendered straight off the page rather than the MP4: held frames are
    then pixel-identical and merge into one, and each frame is encoded whole (ffmpeg's encoder redraws only the
    changed rectangles, which leaves visible seams on the dark gradient)."""
    from PIL import Image, ImageChops
    frames_dir = OUT / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    subprocess.run(["node", str(HERE / "render.js"), str(html), str(frames_dir), "--frames", str(fps), "0.75"], check=True)
    frames, durations, prev = [], [], None
    step = round(1000 / fps)
    for f in sorted(frames_dir.glob("*.png")):
        im = Image.open(f).convert("RGB")
        if prev is not None and ImageChops.difference(im, prev).getbbox() is None:
            durations[-1] += step
            continue
        frames.append(im)
        durations.append(step)
        prev = im
    frames[0].save(VIDEO / "sophia-explainer-preview.webp", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, quality=80, method=5)


if __name__ == "__main__":
    html = page()
    print(html)
    if "--video" in sys.argv:
        video(html)
