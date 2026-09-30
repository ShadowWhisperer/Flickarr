#!/bin/bash

if [[ ! -f '.env' ]]; then
 echo
 echo '[!] .env file missing'
 echo
 echo 'Example: https://raw.githubusercontent.com/ShadowWhisperer/Flickarr/refs/heads/main/.env.example'
 echo
 exit
fi

set -a
source .env
set +a
export DATA_DIR="./data"

python3 main.py
