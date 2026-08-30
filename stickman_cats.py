#!/usr/bin/env python3
"""
Stickman Cat Characters for Podcast Video
Generates animated cat stickmen for each speaker with mouth movement sync.
"""

import math
from PIL import Image, ImageDraw, ImageFont
import numpy as np


class StickmanCat:
    """A simple animated stickman cat character."""

    def __init__(self, name, color="#FFD93D", accent_color="#FF6B6B"):
        self.name = name
        self.color = color
        self.accent_color = accent_color
        self.is_speaking = False
        self.mouth_open = 0.0  # 0.0 to 1.0
        self.bounce_offset = 0.0
        self.eye_blink = False

    def draw(self, draw, x, y, scale=1.0, frame=0):
        """Draw the stickman cat at position (x, y)."""
        s = scale
        bounce = int(self.bounce_offset * 3 * s)

        # Body (circle)
        body_radius = int(25 * s)
        body_y = y + bounce
        draw.ellipse(
            [x - body_radius, body_y - body_radius,
             x + body_radius, body_y + body_radius],
            fill=self.color, outline="#333333", width=int(2 * s)
        )

        # Head (larger circle)
        head_radius = int(20 * s)
        head_y = body_y - body_radius - head_radius + int(5 * s)
        draw.ellipse(
            [x - head_radius, head_y - head_radius,
             x + head_radius, head_y + head_radius],
            fill=self.color, outline="#333333", width=int(2 * s)
        )

        # Ears (triangles)
        ear_size = int(12 * s)
        # Left ear
        draw.polygon([
            (x - head_radius + int(3 * s), head_y - head_radius),
            (x - head_radius + ear_size, head_y - head_radius - ear_size),
            (x - int(5 * s), head_y - head_radius + int(5 * s))
        ], fill=self.accent_color, outline="#333333")
        # Right ear
        draw.polygon([
            (x + head_radius - int(3 * s), head_y - head_radius),
            (x + head_radius - ear_size, head_y - head_radius - ear_size),
            (x + int(5 * s), head_y - head_radius + int(5 * s))
        ], fill=self.accent_color, outline="#333333")

        # Eyes
        eye_y = head_y - int(3 * s)
        eye_offset_x = int(7 * s)
        eye_radius = int(4 * s)

        if self.eye_blink:
            # Blink - just a line
            draw.line(
                [(x - eye_offset_x - eye_radius, eye_y),
                 (x - eye_offset_x + eye_radius, eye_y)],
                fill="#333333", width=int(2 * s)
            )
            draw.line(
                [(x + eye_offset_x - eye_radius, eye_y),
                 (x + eye_offset_x + eye_radius, eye_y)],
                fill="#333333", width=int(2 * s)
            )
        else:
            # Open eyes
            draw.ellipse(
                [x - eye_offset_x - eye_radius, eye_y - eye_radius,
                 x - eye_offset_x + eye_radius, eye_y + eye_radius],
                fill="white", outline="#333333", width=int(1 * s)
            )
            draw.ellipse(
                [x + eye_offset_x - eye_radius, eye_y - eye_radius,
                 x + eye_offset_x + eye_radius, eye_y + eye_radius],
                fill="white", outline="#333333", width=int(1 * s)
            )
            # Pupils
            pupil_radius = int(2 * s)
            pupil_offset = int(1 * s) if not self.is_speaking else int(2 * s)
            draw.ellipse(
                [x - eye_offset_x - pupil_radius + pupil_offset, eye_y - pupil_radius,
                 x - eye_offset_x + pupil_radius + pupil_offset, eye_y + pupil_radius],
                fill="#333333"
            )
            draw.ellipse(
                [x + eye_offset_x - pupil_radius + pupil_offset, eye_y - pupil_radius,
                 x + eye_offset_x + pupil_radius + pupil_offset, eye_y + pupil_radius],
                fill="#333333"
            )

        # Nose
        nose_y = head_y + int(3 * s)
        draw.polygon([
            (x, nose_y),
            (x - int(3 * s), nose_y + int(4 * s)),
            (x + int(3 * s), nose_y + int(4 * s))
        ], fill="#FF6B6B")

        # Mouth
        mouth_y = head_y + int(8 * s)
        mouth_width = int(8 * s)
        mouth_open_height = int(self.mouth_open * 6 * s)

        if self.mouth_open > 0.1:
            # Open mouth (talking)
            draw.ellipse(
                [x - mouth_width, mouth_y - int(2 * s),
                 x + mouth_width, mouth_y + mouth_open_height],
                fill="#333333"
            )
        else:
            # Closed mouth (small line)
            draw.arc(
                [x - mouth_width, mouth_y - int(2 * s),
                 x + mouth_width, mouth_y + int(6 * s)],
                start=0, end=180, fill="#333333", width=int(2 * s)
            )

        # Whiskers
        whisker_length = int(15 * s)
        whisker_y = head_y + int(5 * s)
        for dx in [-1, 1]:
            for dy in [-2, 0, 2]:
                start_x = x + dx * int(8 * s)
                start_y = whisker_y + int(dy * s)
                end_x = start_x + dx * whisker_length
                end_y = start_y + int(dy * s * 0.5)
                draw.line(
                    [(start_x, start_y), (end_x, end_y)],
                    fill="#333333", width=int(1 * s)
                )

        # Arms
        arm_y = body_y - int(5 * s)
        arm_length = int(20 * s)
        arm_angle = 30 if self.is_speaking else 45

        for side in [-1, 1]:
            angle_rad = math.radians(arm_angle * side)
            end_x = x + side * int(arm_length * math.cos(angle_rad))
            end_y = arm_y + int(arm_length * math.sin(angle_rad))
            draw.line(
                [(x + side * body_radius, arm_y), (end_x, end_y)],
                fill="#333333", width=int(3 * s)
            )
            # Paw
            draw.ellipse(
                [end_x - int(4 * s), end_y - int(4 * s),
                 end_x + int(4 * s), end_y + int(4 * s)],
                fill=self.color, outline="#333333", width=int(1 * s)
            )

        # Legs
        leg_y = body_y + body_radius
        leg_length = int(20 * s)
        for side in [-1, 1]:
            end_x = x + side * int(10 * s)
            end_y = leg_y + leg_length
            draw.line(
                [(x + side * int(8 * s), leg_y), (end_x, end_y)],
                fill="#333333", width=int(3 * s)
            )
            # Foot
            draw.ellipse(
                [end_x - int(5 * s), end_y - int(3 * s),
                 end_x + int(7 * s), end_y + int(5 * s)],
                fill=self.color, outline="#333333", width=int(1 * s)
            )

        # Tail (curved line)
        tail_start_x = x + body_radius
        tail_start_y = body_y + int(5 * s)
        tail_points = []
        for i in range(10):
            t = i / 9.0
            tx = tail_start_x + int(25 * s * t)
            ty = tail_start_y - int(20 * s * math.sin(t * math.pi))
            tail_points.append((tx, ty))
        if len(tail_points) > 1:
            draw.line(tail_points, fill="#333333", width=int(3 * s))
            # Tail tip
            last_x, last_y = tail_points[-1]
            draw.ellipse(
                [last_x - int(3 * s), last_y - int(3 * s),
                 last_x + int(3 * s), last_y + int(3 * s)],
                fill=self.accent_color
            )

        return head_y + head_radius  # Return bottom of head for name placement


class PodcastScene:
    """Manages the podcast scene with two cat characters."""

    def __init__(self, width=1280, height=720):
        self.width = width
        self.height = height
        self.bg_color = "#1a1a2e"
        self.accent_color = "#16213e"

        # Create two cat characters
        self.cat1 = StickmanCat("Simba", color="#FFD93D", accent_color="#FF6B6B")
        self.cat2 = StickmanCat("Meow", color="#A8D8EA", accent_color="#AA96DA")

        # Position cats
        self.cat1_x = width // 3
        self.cat2_x = 2 * width // 3
        self.cat_y = height // 2 + 30

    def draw_background(self, draw):
        """Draw the podcast studio background."""
        # Main background
        draw.rectangle([0, 0, self.width, self.height], fill=self.bg_color)

        # Floor
        draw.rectangle(
            [0, self.height - 100, self.width, self.height],
            fill=self.accent_color
        )

        # Microphone stands
        for x in [self.cat1_x, self.cat2_x]:
            # Stand
            draw.line(
                [(x, self.height - 100), (x, self.height - 180)],
                fill="#666666", width=4
            )
            # Mic head
            draw.ellipse(
                [x - 15, self.height - 195, x + 15, self.height - 165],
                fill="#444444", outline="#333333", width=2
            )

    def draw_title(self, draw, title, subtitle=None):
        """Draw the podcast title."""
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except (IOError, OSError):
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Title
        bbox = draw.textbbox((0, 0), title, font=font_large)
        text_width = bbox[2] - bbox[0]
        x = (self.width - text_width) // 2
        draw.text((x, 20), title, fill="#FFFFFF", font=font_large)

        # Subtitle
        if subtitle:
            bbox = draw.textbbox((0, 0), subtitle, font=font_small)
            text_width = bbox[2] - bbox[0]
            x = (self.width - text_width) // 2
            draw.text((x, 60), subtitle, fill="#AAAAAA", font=font_small)

    def draw_speaker_names(self, draw):
        """Draw speaker names under each cat."""
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except (IOError, OSError):
            font = ImageFont.load_default()

        # Cat 1 name
        bbox = draw.textbbox((0, 0), self.cat1.name, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(
            (self.cat1_x - text_width // 2, self.cat_y + 50),
            self.cat1.name,
            fill="#FFD93D" if self.cat1.is_speaking else "#888888",
            font=font
        )

        # Cat 2 name
        bbox = draw.textbbox((0, 0), self.cat2.name, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(
            (self.cat2_x - text_width // 2, self.cat_y + 50),
            self.cat2.name,
            fill="#A8D8EA" if self.cat2.is_speaking else "#888888",
            font=font
        )

    def generate_frame(self, speaker, mouth_open, frame_number=0):
        """Generate a single frame of the animation."""
        img = Image.new("RGB", (self.width, self.height), self.bg_color)
        draw = ImageDraw.Draw(img)

        # Update character states
        self.cat1.is_speaking = (speaker == "Speaker 1")
        self.cat2.is_speaking = (speaker == "Speaker 2")

        if self.cat1.is_speaking:
            self.cat1.mouth_open = mouth_open
            self.cat2.mouth_open = 0.0
            self.cat1.bounce_offset = math.sin(frame_number * 0.3) * 2
            self.cat2.bounce_offset = 0.0
        elif self.cat2.is_speaking:
            self.cat2.mouth_open = mouth_open
            self.cat1.mouth_open = 0.0
            self.cat2.bounce_offset = math.sin(frame_number * 0.3) * 2
            self.cat1.bounce_offset = 0.0
        else:
            self.cat1.mouth_open = 0.0
            self.cat2.mouth_open = 0.0
            self.cat1.bounce_offset = 0.0
            self.cat2.bounce_offset = 0.0

        # Blink randomly
        self.cat1.eye_blink = (frame_number % 60 == 0)
        self.cat2.eye_blink = (frame_number % 60 == 30)

        # Draw everything
        self.draw_background(draw)
        self.draw_title(draw, "The Simba Show", "A Cat Podcast")

        # Draw cats
        self.cat1.draw(draw, self.cat1_x, self.cat_y, scale=1.5, frame=frame_number)
        self.cat2.draw(draw, self.cat2_x, self.cat_y, scale=1.5, frame=frame_number)

        # Draw speaker names
        self.draw_speaker_names(draw)

        return img


def create_animation_frames(lines, seg_durations, seg_dir, fps=24):
    """
    Generate animation frames for the entire video.

    Returns a list of (frame_path, duration) tuples.
    """
    import os

    frames_dir = os.path.join(seg_dir, "animation_frames")
    os.makedirs(frames_dir, exist_ok=True)

    scene = PodcastScene(width=1280, height=720)
    frame_paths = []

    frame_number = 0
    for i, ((speaker, text), duration) in enumerate(zip(lines, seg_durations)):
        # Generate frames for this segment
        num_frames = int(duration * fps)
        if num_frames == 0:
            num_frames = 1

        # Create mouth movement pattern
        # More natural: random-ish movement based on text length
        words = text.split()
        mouth_pattern = []

        for frame_idx in range(num_frames):
            # Create natural mouth movement
            t = frame_idx / num_frames

            # Open mouth during speech, close at pauses
            if frame_idx < num_frames * 0.9:  # Speak for 90% of duration
                # Vary mouth opening
                base_open = 0.5 + 0.3 * math.sin(frame_idx * 0.5)
                # Add some randomness
                if frame_idx % 3 == 0:
                    base_open *= 0.7
                mouth_pattern.append(min(1.0, max(0.1, base_open)))
            else:
                # Close mouth at end
                mouth_pattern.append(0.0)

        # Generate frames
        for frame_idx in range(num_frames):
            mouth_open = mouth_pattern[frame_idx] if frame_idx < len(mouth_pattern) else 0.0

            # Generate frame
            img = scene.generate_frame(speaker, mouth_open, frame_number)

            # Save frame
            frame_path = os.path.join(frames_dir, f"frame_{frame_number:06d}.png")
            img.save(frame_path, "PNG")
            frame_paths.append(frame_path)

            frame_number += 1

    return frame_paths


if __name__ == "__main__":
    # Test the animation
    scene = PodcastScene()
    test_img = scene.generate_frame("Speaker 1", 0.5, 0)
    test_img.save("test_frame.png")
    print("Test frame saved to test_frame.png")
