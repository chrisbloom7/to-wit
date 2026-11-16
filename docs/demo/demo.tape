# README demo: search a past session, read the moment, resume it. Needs `vhs` and `towit` on PATH.
#
#   python3 docs/demo/seed.py        # builds the throwaway home at /tmp/towit-demo
#   vhs docs/demo/demo.tape          # run from the repo root; writes docs/demo/demo.gif
#
# Everything runs against synthetic sessions under /tmp/towit-demo; your own ~/.towit and
# ~/.claude are never read. The session id below is derived by seed.py and stays stable.
# The hidden `towit` function narrows COLUMNS: the search table prints a few columns wider
# than the terminal width it detects, so it would otherwise wrap.

Output docs/demo/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1400
Set Height 560
Set Padding 24
Set TypingSpeed 55ms
Set Theme "Catppuccin Mocha"

Hide
Type "export HOME=/tmp/towit-demo PATH=/tmp/towit-demo/bin:$PATH PS1='$ '" Enter
Type 'towit() { COLUMNS=124 command towit "$@"; }' Enter
Type "cd /tmp/towit-demo/work/acme-api && clear" Enter
Show

Sleep 600ms
Type "# Claude Code deleted that transcript. To Wit kept it." Enter
Sleep 1500ms

Type "towit search jitter" Enter
Sleep 3500ms

Type "towit show 7fac4752-ddf1-51e9-afe3-39a6a96d0b43 --around 6 --context 2" Enter
Sleep 4500ms

Type "towit resume 7fac4752-ddf1-51e9-afe3-39a6a96d0b43" Enter
Sleep 3500ms
