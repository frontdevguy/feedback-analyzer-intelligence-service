#!/bin/bash

# Load environment variables from .env file
set -o allexport
source .env
set +o allexport

# Unset all environment variables listed in .env
while IFS= read -r line; do
  if [[ $line == *=* ]]; then
    var_name=$(echo "$line" | cut -d '=' -f 1)
    unset $var_name
  fi
done < .env

# Start the FastAPI application
uvicorn app:app --host 0.0.0.0 --port 8200 --reload 