#!/bin/sh
# Open data/.alpaca in TextEdit.
#
# A script rather than an `open -e <path>` instruction, because a copied command
# that begins with a word and a flag loses them easily — dropping `open` leaves
# zsh trying to run `-e`, which is not a command. One path, nothing to lose.
cd "$(dirname "$0")"
[ -f data/.alpaca ] || printf '' > data/.alpaca
chmod 600 data/.alpaca
echo "  Opening data/.alpaca in TextEdit."
echo "  Replace the whole file with exactly two lines:"
echo "     line 1: the Key ID     (starts PK)"
echo "     line 2: the Secret Key (shown once at generation)"
echo "  Save with Cmd-S, close the window, then run check-key.sh"
open -e data/.alpaca
