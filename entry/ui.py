"""UI utilities: banner, spinner, ANSI helpers."""

import os
import random
import time
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def type_line(text: str, delay: float = 0.008):
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(delay)
    print()


def print_banner():
    clear_screen()

    CYAN = "\033[38;5;51m"
    PURPLE = "\033[38;5;141m"
    SILVER = "\033[38;5;250m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    WHITE = "\033[37m"

    logo = f"""{CYAN}{BOLD}
███╗   ██╗ █████╗ ███╗   ██╗ ██████╗
████╗  ██║██╔══██╗████╗  ██║██╔═══██╗
██╔██╗ ██║███████║██╔██╗ ██║██║   ██║
██║╚██╗██║██╔══██║██║╚██╗██║██║   ██║
██║ ╚████║██║  ██║██║ ╚████║╚██████╔╝
╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝

 ██████╗██╗      █████╗ ██╗    ██╗
██╔════╝██║     ██╔══██╗██║    ██║
██║     ██║     ███████║██║ █╗ ██║
██║     ██║     ██╔══██║██║███╗██║
╚██████╗███████╗██║  ██║╚███╔███╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
{RESET}"""

    sub_title = f"{WHITE}{BOLD} 👾 Welcome to the {PURPLE}{BOLD}NanoClaw{RESET}{WHITE}{BOLD} !  {RESET}"

    quotes = [
        "It works on my machine.",
        "It compiles! Ship it.",
        "Git commit, push, pray.",
        "There's no place like 127.0.0.1.",
        "sudo make me a sandwich.",
        "Works fine in dev.",
        "May the source be with you.",
        "Ctrl+C, Ctrl+V, Deploy.",
        "Hello, World.",
    ]
    quote = random.choice(quotes)
    meta = f" {SILVER}✦{RESET} {CYAN}{quote}{RESET}"

    tip = (
        f"{PURPLE} ✦ {RESET}"
        f"{SILVER}{PURPLE}{BOLD}NanoClaw{RESET} 已完成启动。输入命令开始，输入 {PURPLE}/exit{RESET}{SILVER} 退出。{RESET}\n"
    )

    print(logo)
    print(sub_title)
    print()
    time.sleep(0.12)
    print(meta)
    print()
    type_line(tip, delay=0.004)


def cprint(text="", end="\n"):
    print_formatted_text(ANSI(str(text)), end=end)


class SpinnerState:
    """Tracks spinner animation state shared between coroutines."""

    action_words = [
        "Thinking...",
        "Working...",
        "Beep boop...",
        "Eating bugs...",
        "Charging battery...",
        "Brewing coffee...",
        "Blinking lights...",
        "Polishing pixels...",
        "Scanning matrix...",
        "Warming up circuits...",
        "Syncing data...",
        "Pinging server...",
    ]

    def __init__(self):
        self.current_words: list[str] = []
        self.is_spinning = False
        self.start_time = 0.0
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.is_tool_calling = False
        self.tool_msg = ""


def get_bottom_toolbar(spinner: SpinnerState) -> ANSI:
    """Render the spinner toolbar line shown below the prompt."""
    if not spinner.is_spinning:
        return ANSI("")

    elapsed = time.time() - spinner.start_time
    if spinner.is_tool_calling:
        display_msg = spinner.tool_msg
    else:
        idx_word = int(elapsed) % len(spinner.current_words)
        display_msg = f"👾 {spinner.current_words[idx_word]}"

    idx_frame = int(elapsed * 12) % len(spinner.frames)
    frame = spinner.frames[idx_frame]

    return ANSI(
        f"  \033[38;5;51m{frame}\033[0m"
        f" \033[38;5;250m{display_msg}\033[0m"
        f" \033[38;5;141m[{elapsed:.1f}s]\033[0m"
    )