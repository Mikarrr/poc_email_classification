#!/bin/sh
# Pulls the base model and creates "<model>-router" with a fixed CPU thread count.
# Using every core is very slow on CPUs with efficiency cores (e.g. Apple Silicon),
# so the default is half of the cores; override it with OLLAMA_NUM_THREAD.
set -eu

threads="${OLLAMA_NUM_THREAD:-$(( $(nproc) / 2 ))}"
[ "$threads" -ge 1 ] || threads=1

ollama pull "$OLLAMA_MODEL"
printf 'FROM %s\nPARAMETER num_thread %s\n' "$OLLAMA_MODEL" "$threads" > /tmp/Modelfile
ollama create "$OLLAMA_MODEL-router" -f /tmp/Modelfile
echo "ready: $OLLAMA_MODEL-router with num_thread=$threads"
