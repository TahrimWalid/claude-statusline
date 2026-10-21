#!/usr/bin/env bash
# Render the statusline for a few sample sessions, using the current directory
# for the git segment. Usage: ./preview.sh [path/to/statusline.sh]
SCRIPT=${1:-"$(dirname "$0")/statusline.sh"}
now=$(date +%s)

show() {  # show TITLE COLUMNS JQ_FILTER
  printf '\n\e[2m── %s (%s columns)\e[0m\n' "$1" "$2"
  jq -nc --argjson now "$now" --arg d "$PWD" "$3"' | .workspace = {current_dir: $d, project_dir: $d}' \
    | COLUMNS=$2 bash "$SCRIPT"
}

show "Normal session" 200 '{session_name: "setup-statusline", model: {display_name: "Opus"},
  effort: {level: "medium"},
  context_window: {used_percentage: 55, context_window_size: 200000, total_input_tokens: 110000, total_output_tokens: 3200},
  cost: {total_cost_usd: 4.12, total_duration_ms: 1503000, total_lines_added: 120, total_lines_removed: 7},
  rate_limits: {five_hour: {used_percentage: 30, resets_at: ($now + 8040)},
                seven_day: {used_percentage: 12, resets_at: ($now + 367200)}}}'

show "Burning through limits, context nearly full" 200 '{session_name: "big-refactor", model: {display_name: "Opus"},
  effort: {level: "high"}, fast_mode: true, agent: {name: "reviewer"},
  context_window: {used_percentage: 93, context_window_size: 200000, total_input_tokens: 186000, total_output_tokens: 9100},
  cost: {total_cost_usd: 11.5, total_duration_ms: 4380000, total_lines_added: 640, total_lines_removed: 212},
  rate_limits: {five_hour: {used_percentage: 70, resets_at: ($now + 10800)},
                seven_day: {used_percentage: 48, resets_at: ($now + 400000)}}}'

show "API key user (no rate limits, cost at full strength)" 200 '{model: {display_name: "Sonnet"},
  context_window: {used_percentage: 22, context_window_size: 1000000, total_input_tokens: 220000, total_output_tokens: 5400},
  cost: {total_cost_usd: 0.87, total_duration_ms: 42000, total_lines_added: 3, total_lines_removed: 0}}'

show "Normal session, narrow terminal" 80 '{session_name: "setup-statusline", model: {display_name: "Opus"},
  effort: {level: "medium"},
  context_window: {used_percentage: 55, context_window_size: 200000, total_input_tokens: 110000, total_output_tokens: 3200},
  cost: {total_cost_usd: 4.12, total_duration_ms: 1503000, total_lines_added: 120, total_lines_removed: 7},
  rate_limits: {five_hour: {used_percentage: 30, resets_at: ($now + 8040)},
                seven_day: {used_percentage: 12, resets_at: ($now + 367200)}}}'
echo
