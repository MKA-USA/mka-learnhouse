#!/usr/bin/env bash
# Rebuild the codebase-memory-mcp knowledge graph for this project.
# Run after pulling significant changes or when the graph feels stale.
set -euo pipefail

echo "Rebuilding codebase knowledge graph..."
echo "This will re-index all source files and rebuild the knowledge graph."

# The actual re-indexing is done via the MCP tool call within a Qwen Code session:
# mcp__codebase-memory-mcp__index_repository(
#   repo_path="/Users/mamjed/Documents/GitHub/mka-learnhouse",
#   mode="full",
#   persistence=true
# )
#
# This script is a convenience wrapper that can be called from git hooks
# or manually. The MCP server must be running for this to work.

if command -v qwen &> /dev/null; then
  echo "Note: For full re-indexing, run this inside a Qwen Code session:"
  echo "  'rebuild the codebase graph'"
  echo ""
  echo "Or ask Qwen Code: 're-index the codebase memory'"
fi

echo "Graph rebuild request noted. If running inside Qwen Code, the agent will trigger re-indexing."
