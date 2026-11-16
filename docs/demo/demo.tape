# README demo: search a past session, read the moment, resume it. Needs `vhs`; it runs this checkout's bin/towit.
#
#   python3 docs/demo/seed.py        # builds the throwaway home at /tmp/towit-demo
#   vhs docs/demo/demo.tape          # run from the repo root; rewrites docs/demo/demo.gif (committed:
#                                    re-render it whenever the CLI output it shows changes)
#
# Everything runs against synthetic sessions under /tmp/towit-demo; your own ~/.towit and
# ~/.claude are never read. The session id below is derived by seed.py and stays stable.
# The hidden `towit` function prints a blank line after each command's output (except `show`,
# which ends with one), so each typed comment stays attached to its command with a gap
# between steps.
#
# The GIF opens and ends on the same title card (docs/demo/banner.py), so it loops without a jump.

Output docs/demo/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1400
Set Height 580
Set Padding 24
Set TypingSpeed 55ms
Set Theme "Catppuccin Mocha"

Hide
Type "export REPO=$PWD HOME=/tmp/towit-demo PATH=$PWD/bin:/tmp/towit-demo/bin:$PATH" Enter
Type 'towit() { command towit "$@"; local rc=$?; [ "$1" = show ] || echo; return $rc; }' Enter
Type "cd /tmp/towit-demo/work/acme-api && clear" Enter
Type `banner() { clear; python3 $REPO/docs/demo/banner.py "to wit" "Search and resume your Claude Code past"; }` Enter
Type "PS1= && banner" Enter
Show

Sleep 2500ms

Hide
Type "tput cnorm && PS1='$ ' && clear" Enter
Show

Sleep 600ms
Type@25ms "# Where did we settle webhook retries? I remember one word: jitter." Enter
Sleep 400ms
Type "towit search jitter" Enter
Sleep 3500ms

Type@25ms "# Read the decision in context: message 6, plus two messages either side." Enter
Sleep 400ms
Type "towit show 7fac4752-ddf1-51e9-afe3-39a6a96d0b43 --around 6 --context 2" Enter
Sleep 4500ms

Type@25ms "# Pick that conversation back up in Claude Code." Enter
Sleep 400ms
Type "towit resume 7fac4752-ddf1-51e9-afe3-39a6a96d0b43" Enter
Sleep 3500ms

Hide
Type "PS1= && banner" Enter
Show
Sleep 2500ms
