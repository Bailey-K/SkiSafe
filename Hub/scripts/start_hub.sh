#!/bin/bash

echo "Killing old hub session..."
tmux kill-session -t hub 2>/dev/null

echo "Creating new hub session..."

# Create detached session
tmux new-session -d -s hub -n reader

# Reader window
tmux send-keys -t hub:reader "python3 ~/skisafe/reader.py" C-m

# App window
tmux new-window -t hub -n app
tmux send-keys -t hub:app "cd ~/skisafe && python3 app.py" C-m

# Ngrok window
tmux new-window -t hub -n ngrok
tmux send-keys -t hub:ngrok "ngrok http 5000" C-m

echo ""
echo "Hub started."
echo ""
echo "View with:"
echo "tmux attach -t hub"
