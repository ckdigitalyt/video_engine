#!/bin/bash
git add .
git commit -m "chore: auto-sync $(date +'%Y-%m-%d %H:%M:%S')"
git push origin main
