#!/bin/bash

if tmux has-session -t hub 2>/dev/null
then
    tmux kill-session -t hub
    echo "Hub stopped."
else
    echo "Hub already stopped."
fi
