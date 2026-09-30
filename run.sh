#!/bin/zsh
# stdio entry point: ssh macmini ~/shop-mcp/run.sh
export PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH  # uv: Homebrew on Apple Silicon or Intel, or its own installer
exec uv run --quiet --script "$HOME/shop-mcp/server.py"
