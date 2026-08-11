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
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

VOICE_SPEAKER1 = "en-US-ChristopherNeural"  # Simba
VOICE_SPEAKER2 = "en-US-JennyNeural"        # Meow
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


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


async def synth_segment(text, voice, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate="-8%")
    await communicate.save(out_path)


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


def make_srt(lines, seg_durations, out_path):
    """Build SRT from segments."""
    entries = []
    t = 0.0
    for i, ((speaker, text), dur) in enumerate(zip(lines, seg_durations)):
        start, end = t, t + dur
        t = end + 0.3
        s = f"{int(start//3600):02d}:{int(start%3600//60):02d}:{int(start%60):02d},{int(start%1*1000):03d}"
        e = f"{int(end//3600):02d}:{int(end%3600//60):02d}:{int(end%60):02d},{int(end%1*1000):03d}"
        entries.append(f"{i+1}\n{s} --> {e}\n{text}\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))


def make_thumbnail(title, out_path):
    """Simple thumbnail with ffmpeg."""
    safe_title = title[:40].replace("'", "").replace('"', "").replace(":", "")
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#1a1a2e:s=1280x720:d=1",
            "-vf", (
                "drawtext=text='Cat Podcast':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=h/2-80,"
                f"drawtext=text='{safe_title}':fontcolor=#ffaa00:fontsize=40:x=(w-text_w)/2:y=h/2+20"
            ),
            "-frames:v", "1", out_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception:
        pass
    return out_path if os.path.exists(out_path) else None


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

    # 1. Synthesize per-segment audio
    seg_dir = ensure_dir(os.path.join(out_dir, "segments"))
    seg_paths = []
    print("Synthesizing audio...")
    for i, (speaker, text) in enumerate(lines):
        voice = VOICE_SPEAKER1 if "1" in speaker else VOICE_SPEAKER2
        seg = os.path.join(seg_dir, f"seg_{i:04d}.mp3")
        asyncio.run(synth_segment(text, voice, seg))
        seg_paths.append(seg)

    # 2. Concatenate
    concat = os.path.join(seg_dir, "concat.txt")
    with open(concat, "w", encoding="utf-8") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
    raw_audio = os.path.join(out_dir, "raw_audio.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
                    "-c:a", "libmp3lame", raw_audio], capture_output=True, text=True, timeout=300)

    # 3. Subtitles
    durations = [get_audio_duration(p) for p in seg_paths]
    srt_path = os.path.join(out_dir, "subtitles.srt")
    make_srt(lines, durations, srt_path)

    # 4. Build video (Ken Burns over color bg)
    total_dur = sum(durations) + 0.3 * (len(durations) - 1)
    video_path = os.path.join(out_dir, "final_video.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=#1a1a2e:s=1280x720:d={total_dur}",
        "-i", raw_audio,
        "-vf", f"subtitles={srt_path}:force_style='FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Alignment=2,MarginV=40'",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
        "-shortest", video_path,
    ]
    print("Building video...")
    subprocess.run(cmd, capture_output=True, text=True, timeout=600)

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
