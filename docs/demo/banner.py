#!/usr/bin/env python3
"""Print a title card: big block letters with a color gradient, then a tagline. Centered in the terminal. Usage: banner.py NAME [TAGLINE]
Pure standard library; hides the cursor when done (restore with `tput cnorm`), so a demo needs no figlet. Prints one row at a time so it can be revealed on screen."""
import shutil, sys, time
F = {
 'A':["  █  "," █ █ ","█████","█   █","█   █"], 'B':["████ ","█   █","████ ","█   █","████ "],
 'C':[" ████","█    ","█    ","█    "," ████"], 'D':["████ ","█   █","█   █","█   █","████ "],
 'E':["█████","█    ","████ ","█    ","█████"], 'F':["█████","█    ","████ ","█    ","█    "],
 'G':[" ████","█    ","█  ██","█   █"," ████"], 'H':["█   █","█   █","█████","█   █","█   █"],
 'I':["█████","  █  ","  █  ","  █  ","█████"], 'J':["█████","   █ ","   █ ","█  █ "," ██  "],
 'K':["█   █","█  █ ","███  ","█  █ ","█   █"], 'L':["█    ","█    ","█    ","█    ","█████"],
 'M':["█   █","██ ██","█ █ █","█   █","█   █"], 'N':["█   █","██  █","█ █ █","█  ██","█   █"],
 'O':[" ███ ","█   █","█   █","█   █"," ███ "], 'P':["████ ","█   █","████ ","█    ","█    "],
 'Q':[" ███ ","█   █","█ █ █","█  █ "," ██ █"], 'R':["████ ","█   █","████ ","█  █ ","█   █"],
 'S':[" ████","█    "," ███ ","    █","████ "], 'T':["█████","  █  ","  █  ","  █  ","  █  "],
 'U':["█   █","█   █","█   █","█   █"," ███ "], 'V':["█   █","█   █","█   █"," █ █ ","  █  "],
 'W':["█   █","█   █","█ █ █","██ ██","█   █"], 'X':["█   █"," █ █ ","  █  "," █ █ ","█   █"],
 'Y':["█   █"," █ █ ","  █  ","  █  ","  █  "], 'Z':["█████","   █ ","  █  "," █   ","█████"],
 '-':["     ","     ","█████","     ","     "], ' ':["   "]*5,
}
name = sys.argv[1].upper(); tag = sys.argv[2] if len(sys.argv) > 2 else ""
rows = ["  ".join(F[c][r] for c in name) for r in range(5)]
width = max(len(r) for r in rows)
def grad(x):  # 256-color ramp, magenta to cyan, left to right
    ramp = [201, 165, 129, 93, 63, 33, 39, 45, 51]
    return ramp[min(len(ramp) - 1, int(x / max(width, 1) * len(ramp)))]
cols, lines = shutil.get_terminal_size((100, 30))
left = " " * max(0, (cols - width) // 2)
print("\n" * max(0, (lines - len(rows) - (2 if tag else 0)) // 2 - 1))
for r in rows:
    print(left + "".join(f"\033[38;5;{grad(i)}m{ch}\033[0m" if ch != " " else " " for i, ch in enumerate(r)), flush=True)
    time.sleep(0.12)
if tag:
    print("\n" + " " * max(0, (cols - len(tag)) // 2) + f"\033[2m{tag}\033[0m", flush=True)
print("\033[?25l", end="", flush=True)  # hide the cursor while the card shows; the tape restores it with `tput cnorm`
