#!/usr/bin/env python3
"""Record a reproducible Snatch demo from an isolated Herdr session.

Run with: uv run --with pyte --with pillow python demo/record.py
"""

import fcntl
import json
import os
import pty
import secrets
import select
import struct
import subprocess
import tempfile
import termios
import time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont


COLS, ROWS = 96, 28
FPS = 12
FONT = "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf"
FONT_SIZE = 17
CELL_W, CELL_H = 11, 21
BACKGROUND = "#151a22"
FOREGROUND = "#e0e5ec"
COLORS = {
    "black": "#151a22", "red": "#e06c75", "green": "#98c379", "yellow": "#e5c07b",
    "blue": "#61afef", "magenta": "#c678dd", "cyan": "#56b6c2", "white": "#e0e5ec",
    "brightblack": "#5c6370", "brightred": "#e06c75", "brightgreen": "#98c379",
    "brightyellow": "#e5c07b", "brightblue": "#61afef", "brightmagenta": "#c678dd",
    "brightcyan": "#56b6c2", "brightwhite": "#ffffff",
}


def cli(session, *args):
    output = subprocess.run(
        ["herdr", "--session", session, *args], check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(output)["result"] if output.strip() else {}


def color(value, default):
    if value == "default":
        return default
    if value.startswith("#") and len(value) == 7:
        return value
    return COLORS.get(value, default)


def render(screen, font):
    image = Image.new("RGB", (COLS * CELL_W, ROWS * CELL_H), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for row in range(ROWS):
        for col in range(COLS):
            cell = screen.buffer[row][col]
            foreground = color(cell.fg, FOREGROUND)
            background = color(cell.bg, BACKGROUND)
            if cell.reverse:
                foreground, background = background, foreground
            x, y = col * CELL_W, row * CELL_H
            if background != BACKGROUND:
                draw.rectangle((x, y, x + CELL_W, y + CELL_H), fill=background)
            if cell.data != " ":
                draw.text((x, y), cell.data, font=font, fill=foreground)
    if not screen.cursor.hidden:
        x, y = screen.cursor.x * CELL_W, screen.cursor.y * CELL_H
        draw.rectangle((x, y + CELL_H - 3, x + CELL_W - 1, y + CELL_H - 1), fill="#ffffff")
    return image


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "demo" / "snatch.mp4"
    preview = root / "demo" / "snatch.gif"
    session = "snatch-demo-" + secrets.token_hex(4)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("HERDR_"):
            environment.pop(key)
    environment["TERM"] = "xterm-256color"
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.Stream(screen)
    frames = []

    def pump(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            readable, _, _ = select.select([master], [], [], min(0.05, until - time.monotonic()))
            if readable:
                try:
                    stream.feed(os.read(master, 65536).decode("utf-8", "replace"))
                except OSError:
                    break

    def hold(seconds):
        pump(0.15)
        frames.extend([render(screen, font)] * round(seconds * FPS))

    font = ImageFont.truetype(FONT, FONT_SIZE)
    with tempfile.TemporaryDirectory(prefix="snatch-demo-files-") as directory:
        fixture = Path(directory)
        (fixture / "src/foo").mkdir(parents=True)
        (fixture / "src/foo/parser.rs").write_text("// demo file\n")
        client = subprocess.Popen(
            ["herdr", "--session", session], cwd=fixture, env=environment,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        os.close(slave)
        try:
            pump(1.2)
            workspace = cli(session, "workspace", "list")["workspaces"][0]
            pane = cli(session, "pane", "list", "--workspace", workspace["workspace_id"])["panes"][0]["pane_id"]
            cli(session, "workspace", "rename", workspace["workspace_id"], "demo")
            cli(session, "pane", "rename", pane, "shell")
            cli(session, "pane", "run", pane,
                "export PS1='$ '; clear; printf 'Compiling demo...\\nerror: src/foo/parser.rs\\nsee https://example.com/issues/123\\ncommit abc123def456\\n'")
            pump(0.6)
            os.write(master, b"vim ")
            hold(0.9)

            os.write(master, b"\x00")  # Ctrl+Space, Herdr's configured prefix.
            pump(0.2)
            os.write(master, b"\t")
            pump(1.0)
            if "tab/visible" not in "\n".join(screen.display):
                raise RuntimeError("prefix+Tab did not open Snatch; check the Herdr keybinding")
            hold(0.6)
            for letter in "pars":
                os.write(master, letter.encode())
                hold(0.22)
            hold(0.8)
            os.write(master, b"\r")
            pump(0.5)
            visible = subprocess.run(
                ["herdr", "--session", session, "pane", "read", pane, "--source", "visible"],
                check=True, capture_output=True, text=True,
            ).stdout
            if "vim src/foo/parser.rs" not in visible:
                raise RuntimeError(f"selection was not inserted into the original pane:\n{visible}")
            hold(1.5)

            with tempfile.TemporaryDirectory(prefix="snatch-demo-frames-") as image_dir:
                for index, frame in enumerate(frames):
                    frame.save(Path(image_dir) / f"{index:04}.png")
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS),
                    "-i", str(Path(image_dir) / "%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(output),
                ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(output),
                "-filter_complex", "fps=8,scale=960:-1:flags=lanczos,split[a][b];"
                "[a]palettegen=max_colors=64:stats_mode=diff[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=5",
                str(preview),
            ], check=True)
            print(output, preview, sep="\n")
        finally:
            client.terminate()
            try:
                client.wait(timeout=3)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
            os.close(master)
            subprocess.run(["herdr", "session", "stop", session], capture_output=True)
            subprocess.run(["herdr", "session", "delete", session], capture_output=True)


if __name__ == "__main__":
    main()
