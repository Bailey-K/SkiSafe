#!/bin/bash

echo "================================="
echo " SkiSafe Hub Status"
echo "================================="
echo

# 1. Check TMUX Session
if tmux has-session -t hub 2>/dev/null
then
    echo "TMUX Session: RUNNING"
else
    echo "TMUX Session: STOPPED"
    exit 1
fi

echo

# 2. Check Background Python Processes & Ngrok
for process in "reader.py" "app.py" "ngrok"; do
    # Capitalize first letter for display
    display_name=$(echo "$process" | awk '{print toupper(substr($1,1,1)) substr($1,2)}')
    
    if pgrep -f "$process" >/dev/null
    then
        echo "$display_name: RUNNING"
    else
        echo "$display_name: STOPPED"
    fi
done

echo

# 3. Check if Port 5000 is listening
if ss -tln | grep -q ":5000"
then
    echo "Port 5000: LISTENING"
else
    echo "Port 5000: NOT LISTENING"
fi

echo

# 4. Fetch Ngrok URL safely
# Tries jq first (best practice). Filters explicitly for the tunnel targeting port 5000.
if command -v jq &> /dev/null; then
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels \
    | jq -r '.tunnels[] | select(.config.addr | endswith(":5000")).public_url' 2>/dev/null | head -n1)
else
    # Fallback to an improved regex grep if jq is missing
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels \
    | grep -o 'https://[^"]*' \
    | head -n1)
fi

# Print Ngrok URL Output
if [ -n "$NGROK_URL" ] && [ "$NGROK_URL" != "null" ]
then
    echo "Public URL:"
    echo "$NGROK_URL"
else
    echo "Public URL: NOT AVAILABLE (Is Ngrok fully booted?)"
fi

echo
echo "TMUX Windows:"
tmux list-windows -t hub 2>/dev/null || echo "No windows found."

echo
echo "Attach:"
echo "tmux attach -t hub"
