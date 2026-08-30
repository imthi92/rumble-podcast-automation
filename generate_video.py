#!/usr/bin/env python3
"""
Standalone episode generator for Rumble automation.
Produces a video from a script using free edge-tts + ffmpeg. No API keys needed.

Usage:
    python generate_video.py <script.txt> [output.mp4]

Output: final_video.mp4 (and thumbnail.png) in ./output
"""

import os
import sys
import asyncio
import json
import subprocess
from pathlib import Path
from datetime import datetime
from stickman_cats import create_animation_frames

VOICE_SPEAKER1 = "en-US-ChristopherNeural"  # Simba
VOICE_SPEAKER2 = "en-US-JennyNeural"        # Meow
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

TTS_CONCURRENCY = 5
TTS_MAX_RETRIES = 3
ANIMATION_FPS = 24


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def parse_script(script_path):
    """Parse script into list of (speaker, text)."""
    lines = []
    with open(script_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or ":" not in line:
                continue
            speaker, text = line.split(":", 1)
            text = text.strip()
            if text:
                lines.append((speaker.strip(), text))
    return lines


async def _synth_one(text, voice, out, sem, attempts=TTS_MAX_RETRIES):
    """Synthesize a single segment with retries, respecting the concurrency limit."""
    import edge_tts

    for attempt in range(1, attempts + 1):
        try:
            async with sem:
                communicate = edge_tts.Communicate(text, voice, rate="-8%")
                await communicate.save(out)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                return
            print(f"  ! empty audio for {os.path.basename(out)} (attempt {attempt})")
        except Exception as e:
            print(f"  ! TTS failed for {os.path.basename(out)} (attempt {attempt}): {e}")
        await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"Could not synthesize {os.path.basename(out)} after {attempts} attempts")


async def _synth_all(lines, voice1, voice2, seg_dir):
    """Synthesize all segments concurrently with a bounded semaphore."""
    sem = asyncio.Semaphore(TTS_CONCURRENCY)
    tasks = []
    paths = []
    for i, (speaker, text) in enumerate(lines):
        voice = voice1 if "1" in speaker else voice2
        out = os.path.join(seg_dir, f"seg_{i:04d}.mp3")
        tasks.append(_synth_one(text, voice, out, sem))
        paths.append(out)
    await asyncio.gather(*tasks)
    return paths


def get_audio_duration(path):
    """Get duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except Exception:
        return 30


def fmt_srt(seconds):
    ms = int(seconds * 1000)
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(lines, seg_durations, out_path):
    """Build SRT from segments (back-to-back, matching the concatenated audio exactly)."""
    entries = []
    t = 0.0
    for i, ((speaker, text), dur) in enumerate(zip(lines, seg_durations)):
        start, end = t, t + dur
        t = end
        entries.append(f"{i+1}\n{fmt_srt(start)} --> {fmt_srt(end)}\n{text}\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))


def sanitize_drawtext(text):
    """Remove characters that break ffmpeg drawtext filters."""
    return "".join(c for c in text if c.isalnum() or c in " _-").strip() or "Untitled"


def make_thumbnail(title, out_path):
    """Generate thumbnail with stickman cats. Falls back to a plain color image
    if animation generation fails."""
    try:
        from stickman_cats import PodcastScene

        scene = PodcastScene(width=1280, height=720)
        img = scene.generate_frame("Speaker 1", 0.0, 0)
        img.save(out_path, "PNG")

        if os.path.exists(out_path):
            print("  Thumbnail generated with stickman cats.")
            return out_path
    except Exception as e:
        print(f"  ! Thumbnail animation failed: {e}")

    # Fallback: plain color thumbnail (valid PNG, no text needed)
    try:
        plain = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#1a1a2e:s=1280x720:d=1",
            "-frames:v", "1", "-q:v", "2", out_path,
        ]
        result = subprocess.run(plain, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(out_path):
            print("  Thumbnail generated without text (fonts unavailable).")
            return out_path
    except Exception as e:
        print(f"  ! Thumbnail fallback failed: {e}")
    return None


def run_ffmpeg(cmd, timeout=600, cwd=None):
    """Run ffmpeg and return True on success."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if result.returncode != 0:
        print(f"  ! ffmpeg stderr: {result.stderr[-500:]}")
        return False
    return True


def main(script_path, episode_title=None):
    if not os.path.exists(script_path):
        print(f"ERROR: script not found: {script_path}")
        sys.exit(1)

    if not episode_title:
        episode_title = Path(script_path).stem.replace("_", " ").title()

    print(f"Generating episode: {episode_title}")
    lines = parse_script(script_path)
    if not lines:
        print("ERROR: no valid 'Speaker: text' lines found in script")
        sys.exit(1)
    print(f"Parsed {len(lines)} lines")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ensure_dir(os.path.join(OUTPUT_DIR, f"episode_{ts}"))
    seg_dir = ensure_dir(os.path.join(out_dir, "segments"))

    # 1. Synthesize all segments in one event loop
    print("Synthesizing audio...")
    try:
        seg_paths = asyncio.run(_synth_all(lines, VOICE_SPEAKER1, VOICE_SPEAKER2, seg_dir))
    except Exception as e:
        print(f"ERROR: audio synthesis failed: {e}")
        sys.exit(1)

    for p in seg_paths:
        if not os.path.exists(p):
            print(f"ERROR: missing segment {p}")
            sys.exit(1)

    # 2. Concatenate (use forward slashes for the concat list)
    concat = os.path.join(seg_dir, "concat.txt")
    with open(concat, "w", encoding="utf-8") as f:
        for p in seg_paths:
            f.write(f"file '{p.replace(os.sep, '/')}'\n")
    raw_audio = os.path.join(out_dir, "raw_audio.mp3")
    if not run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
                       "-c:a", "libmp3lame", "-q:a", "2", raw_audio], timeout=300):
        print("ERROR: audio concat failed")
        sys.exit(1)

    # 3. Subtitles
    durations = [get_audio_duration(p) for p in seg_paths]
    srt_path = os.path.join(out_dir, "subtitles.srt")
    make_srt(lines, durations, srt_path)

    # 4. Build video with animated stickman cats (duration from the actual concatenated audio)
    total_dur = get_audio_duration(raw_audio)
    video_path = os.path.join(out_dir, "final_video.mp4")

    print("Generating stickman cat animations...")
    try:
        # Generate animation frames
        frame_paths = create_animation_frames(lines, durations, seg_dir, fps=ANIMATION_FPS)

        if not frame_paths:
            print("ERROR: No animation frames generated, falling back to static background")
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=#1a1a2e:s=1280x720:d={total_dur}",
                "-i", raw_audio,
                "-vf", "subtitles=subtitles.srt:force_style='FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Alignment=2,MarginV=40'",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest", video_path,
            ]
            if not run_ffmpeg(cmd, timeout=600, cwd=out_dir):
                print("ERROR: video generation failed")
                sys.exit(1)
        else:
            # Create video from frames
            frames_dir = os.path.join(seg_dir, "animation_frames")
            cmd = [
                "ffmpeg", "-y",
                "-framerate", str(ANIMATION_FPS),
                "-i", os.path.join(frames_dir, "frame_%06d.png"),
                "-i", raw_audio,
                "-vf", "subtitles=subtitles.srt:force_style='FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Alignment=2,MarginV=40'",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-shortest", video_path,
            ]
            if not run_ffmpeg(cmd, timeout=600, cwd=out_dir):
                print("ERROR: video generation failed")
                sys.exit(1)

            # Cleanup animation frames to save disk space
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)
            print("Animation frames cleaned up")

    except Exception as e:
        print(f"ERROR: Animation generation failed: {e}")
        print("Falling back to static background...")
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=#1a1a2e:s=1280x720:d={total_dur}",
            "-i", raw_audio,
            "-vf", "subtitles=subtitles.srt:force_style='FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Alignment=2,MarginV=40'",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest", video_path,
        ]
        if not run_ffmpeg(cmd, timeout=600, cwd=out_dir):
            print("ERROR: video generation failed")
            sys.exit(1)

    # 5. Thumbnail
    thumb_path = make_thumbnail(episode_title, os.path.join(out_dir, "thumbnail.png"))

    if not os.path.exists(video_path):
        print("ERROR: video generation failed")
        sys.exit(1)

    print(f"Video: {video_path}")
    print(f"Thumbnail: {thumb_path}")
    print(f"Title: {episode_title}")

    # Save metadata
    with open(os.path.join(out_dir, "metadata.json"), "w") as f:
        json.dump({
            "title": episode_title,
            "video": video_path,
            "thumbnail": thumb_path,
            "script": script_path,
            "timestamp": ts,
        }, f, indent=2)

    print(f"Metadata: {os.path.join(out_dir, 'metadata.json')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_video.py <script.txt> [episode_title]")
        sys.exit(1)
    title = sys.argv[2] if len(sys.argv) > 2 else None
    main(sys.argv[1], title)
