#!/bin/bash
set -e
echo "Pulling latest from GitHub..."
cd ~/skisafe-repo && git pull
echo "Copying hub files..."
cp Hub/app.py ~/skisafe/app.py
cp Hub/reader.py ~/skisafe/reader.py
cp -r Hub/templates ~/skisafe/templates
echo "Done. Restart app.py and reader.py."
