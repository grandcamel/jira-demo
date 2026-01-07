#!/bin/bash
# =============================================================================
# JIRA Demo Auto-Play Script (Streaming Version)
# =============================================================================
# Plays through scenario prompts using Claude's streaming API for reliable,
# visually pleasing output. Replaces the buggy expect-based approach.
#
# Usage:
#   ./autoplay.sh <scenario>                    # Press-key to advance
#   ./autoplay.sh --auto-advance <scenario>     # Auto-advance with 3s delay
#   ./autoplay.sh --auto-advance --delay 5 <scenario>  # Custom delay
#   ./autoplay.sh --show-tools <scenario>       # Show tool usage sub-boxes
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCENARIOS_DIR="${SCENARIOS_DIR:-/workspace/scenarios}"
PACING_MODE="keypress"  # or "auto"
AUTO_DELAY=3            # seconds between prompts in auto mode
SCENARIO=""
MAX_RESULT_LINES=10     # truncate tool results to this many lines
SHOW_TOOLS="${AUTOPLAY_SHOW_TOOLS:-false}"   # show tool use sub-boxes (env or --show-tools)
DEBUG_MODE="${AUTOPLAY_DEBUG:-false}"        # debug mode (env or --debug)
DEBUG_LOG="/tmp/autoplay-debug.log"
OTEL_ENDPOINT="${OTEL_ENDPOINT:-}"           # OTEL/Loki endpoint for log shipping

# =============================================================================
# Colors and Styling
# =============================================================================

# Reset
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_DIM='\033[2m'

# User bubble (blue theme)
C_USER_BORDER='\033[1;34m'
C_USER_LABEL='\033[1;97;44m'
C_USER_TEXT='\033[0;37m'

# Claude bubble (green theme)
C_CLAUDE_BORDER='\033[1;32m'
C_CLAUDE_LABEL='\033[1;97;42m'
C_CLAUDE_TEXT='\033[0;37m'

# Tool sections (yellow theme)
C_TOOL_BORDER='\033[0;33m'
C_TOOL_NAME='\033[1;33m'
C_TOOL_INPUT='\033[0;36m'
C_TOOL_OUTPUT='\033[0;90m'

# Status colors
C_RED='\033[0;31m'
C_YELLOW='\033[1;33m'
C_GREEN='\033[0;32m'
C_CYAN='\033[0;36m'

# Box-drawing characters (Unicode)
BOX_TL='╭'
BOX_TR='╮'
BOX_BL='╰'
BOX_BR='╯'
BOX_H='─'
BOX_V='│'
DIV_L='├'
DIV_R='┤'

# Nested box characters
NBOX_TL='┌'
NBOX_TR='┐'
NBOX_BL='└'
NBOX_BR='┘'

# =============================================================================
# State Variables
# =============================================================================

declare -a DESCRIPTIONS=()
declare -a PROMPTS=()
PAUSED=false
TERMINAL_WIDTH=80

# =============================================================================
# Debug Functions
# =============================================================================

# Buffer for OTEL logs (newline-separated JSON)
OTEL_LOG_BUFFER=""

debug_log() {
    if [[ "$DEBUG_MODE" == true ]]; then
        local timestamp
        timestamp=$(date '+%H:%M:%S')
        local msg="[$timestamp] $*"
        echo "$msg" >> "$DEBUG_LOG"

        # Also buffer for OTEL if endpoint configured
        if [[ -n "$OTEL_ENDPOINT" ]]; then
            local ns_timestamp
            ns_timestamp=$(date +%s%N)
            # Escape the message for JSON
            local escaped_msg
            escaped_msg=$(echo "$*" | jq -Rs '.')
            OTEL_LOG_BUFFER+="[\"${ns_timestamp}\",${escaped_msg}],"
        fi
    fi
}

debug_json() {
    if [[ "$DEBUG_MODE" == true ]]; then
        echo "---JSON---" >> "$DEBUG_LOG"
        echo "$1" >> "$DEBUG_LOG"
        echo "---END---" >> "$DEBUG_LOG"

        # For OTEL, send compact version
        if [[ -n "$OTEL_ENDPOINT" ]]; then
            local ns_timestamp
            ns_timestamp=$(date +%s%N)
            # Get event type for the log
            local event_type
            event_type=$(echo "$1" | jq -r '.type // "unknown"' 2>/dev/null)
            local compact
            compact=$(echo "$1" | jq -c '.' 2>/dev/null || echo "$1")
            local escaped
            escaped=$(echo "JSON[$event_type]: $compact" | jq -Rs '.')
            OTEL_LOG_BUFFER+="[\"${ns_timestamp}\",${escaped}],"
        fi
    fi
}

# Send buffered logs to Loki
flush_otel_logs() {
    if [[ -z "$OTEL_ENDPOINT" ]] || [[ -z "$OTEL_LOG_BUFFER" ]]; then
        return 0
    fi

    # Remove trailing comma and wrap in array
    local values="[${OTEL_LOG_BUFFER%,}]"

    # Build Loki push payload
    local payload
    payload=$(cat <<EOF
{
  "streams": [{
    "stream": {
      "job": "autoplay",
      "scenario": "${SCENARIO:-unknown}",
      "source": "autoplay.sh"
    },
    "values": ${values}
  }]
}
EOF
)

    # Send to Loki (fire and forget)
    curl -s -X POST \
        -H "Content-Type: application/json" \
        "${OTEL_ENDPOINT}/loki/api/v1/push" \
        -d "$payload" >/dev/null 2>&1 &

    # Clear buffer
    OTEL_LOG_BUFFER=""
}

init_debug() {
    if [[ "$DEBUG_MODE" == true ]]; then
        echo "========================================" > "$DEBUG_LOG"
        echo "Autoplay Debug Log - $(date)" >> "$DEBUG_LOG"
        echo "Scenario: $SCENARIO" >> "$DEBUG_LOG"
        echo "OTEL Endpoint: ${OTEL_ENDPOINT:-none}" >> "$DEBUG_LOG"
        echo "========================================" >> "$DEBUG_LOG"
        echo -e "${C_YELLOW}Debug mode enabled. Log: ${DEBUG_LOG}${C_RESET}"
        if [[ -n "$OTEL_ENDPOINT" ]]; then
            echo -e "${C_YELLOW}OTEL logging: ${OTEL_ENDPOINT}${C_RESET}"
        fi
    fi
}

# =============================================================================
# Utility Functions
# =============================================================================

get_terminal_width() {
    TERMINAL_WIDTH=$(tput cols 2>/dev/null || echo 80)
    # Cap at reasonable width for readability
    if [[ $TERMINAL_WIDTH -gt 100 ]]; then
        TERMINAL_WIDTH=100
    fi
}

repeat_char() {
    local char="$1"
    local count="$2"
    local result=""
    for ((i=0; i<count; i++)); do
        result+="$char"
    done
    printf "%s" "$result"
}

# =============================================================================
# Box Drawing Functions
# =============================================================================

draw_box_top() {
    local color="$1"
    local width=$((TERMINAL_WIDTH - 2))
    echo -e "${color}${BOX_TL}$(repeat_char "$BOX_H" "$width")${BOX_TR}${C_RESET}"
}

draw_box_header() {
    local color="$1"
    local label="$2"
    local width=$((TERMINAL_WIDTH - 2))
    local label_len=${#label}
    local padding=$((width - label_len - 2))
    echo -e "${color}${BOX_V}${C_RESET}  ${C_BOLD}${label}${C_RESET}$(repeat_char ' ' "$padding")${color}${BOX_V}${C_RESET}"
}

draw_box_divider() {
    local color="$1"
    local width=$((TERMINAL_WIDTH - 2))
    echo -e "${color}${DIV_L}$(repeat_char "$BOX_H" "$width")${DIV_R}${C_RESET}"
}

draw_box_line() {
    local color="$1"
    local content="$2"
    local width=$((TERMINAL_WIDTH - 2))
    # Strip ANSI codes for length calculation
    local plain_content
    plain_content=$(echo -e "$content" | sed 's/\x1b\[[0-9;]*m//g')
    local content_len=${#plain_content}
    local padding=$((width - content_len - 2))
    if [[ $padding -lt 0 ]]; then
        padding=0
        # Truncate content if too long
        content="${content:0:$((width - 5))}..."
    fi
    echo -e "${color}${BOX_V}${C_RESET}  ${content}$(repeat_char ' ' "$padding")${color}${BOX_V}${C_RESET}"
}

draw_box_empty() {
    local color="$1"
    local width=$((TERMINAL_WIDTH - 2))
    echo -e "${color}${BOX_V}${C_RESET}$(repeat_char ' ' "$width")${color}${BOX_V}${C_RESET}"
}

draw_box_bottom() {
    local color="$1"
    local width=$((TERMINAL_WIDTH - 2))
    echo -e "${color}${BOX_BL}$(repeat_char "$BOX_H" "$width")${BOX_BR}${C_RESET}"
}

# =============================================================================
# Nested Tool Box Functions
# =============================================================================

draw_tool_box_top() {
    local label="$1"
    local width=$((TERMINAL_WIDTH - 8))
    local label_str="${NBOX_TL}${BOX_H} ${C_TOOL_NAME}${label}${C_TOOL_BORDER} "
    local label_plain_len=$((${#label} + 4))
    local remaining=$((width - label_plain_len))
    echo -e "${C_CLAUDE_BORDER}${BOX_V}${C_RESET}  ${C_TOOL_BORDER}${label_str}$(repeat_char "$BOX_H" "$remaining")${NBOX_TR}${C_RESET}  ${C_CLAUDE_BORDER}${BOX_V}${C_RESET}"
}

draw_tool_box_line() {
    local content="$1"
    local width=$((TERMINAL_WIDTH - 8))
    local plain_content
    plain_content=$(echo -e "$content" | sed 's/\x1b\[[0-9;]*m//g')
    local content_len=${#plain_content}
    local padding=$((width - content_len - 2))
    if [[ $padding -lt 0 ]]; then
        padding=0
        content="${content:0:$((width - 5))}..."
    fi
    echo -e "${C_CLAUDE_BORDER}${BOX_V}${C_RESET}  ${C_TOOL_BORDER}${BOX_V}${C_RESET} ${content}$(repeat_char ' ' "$padding")${C_TOOL_BORDER}${BOX_V}${C_RESET}  ${C_CLAUDE_BORDER}${BOX_V}${C_RESET}"
}

draw_tool_box_bottom() {
    local width=$((TERMINAL_WIDTH - 8))
    echo -e "${C_CLAUDE_BORDER}${BOX_V}${C_RESET}  ${C_TOOL_BORDER}${NBOX_BL}$(repeat_char "$BOX_H" "$width")${NBOX_BR}${C_RESET}  ${C_CLAUDE_BORDER}${BOX_V}${C_RESET}"
}

# =============================================================================
# High-Level Display Functions
# =============================================================================

display_user_bubble() {
    local prompt="$1"
    echo ""
    draw_box_top "$C_USER_BORDER"
    draw_box_header "$C_USER_BORDER" "USER"
    draw_box_divider "$C_USER_BORDER"

    # Handle multi-line prompts
    while IFS= read -r line; do
        draw_box_line "$C_USER_BORDER" "$line"
    done <<< "$prompt"

    draw_box_bottom "$C_USER_BORDER"
    echo ""
}

display_claude_header() {
    draw_box_top "$C_CLAUDE_BORDER"
    draw_box_header "$C_CLAUDE_BORDER" "CLAUDE"
    draw_box_divider "$C_CLAUDE_BORDER"
}

display_claude_footer() {
    draw_box_bottom "$C_CLAUDE_BORDER"
}

display_step_header() {
    local step="$1"
    local total="$2"
    local description="$3"

    echo ""
    echo -e "${C_BOLD}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
    echo -e "${C_YELLOW}Step ${step}/${total}:${C_RESET} ${C_BOLD}${description}${C_RESET}"
    echo -e "${C_BOLD}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
}

display_completion() {
    echo ""
    echo -e "${C_GREEN}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
    echo -e "${C_GREEN}${C_BOLD}  Scenario complete!${C_RESET}"
    echo -e "${C_GREEN}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
    echo ""
}

display_error() {
    local message="$1"
    echo ""
    echo -e "${C_RED}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
    echo -e "${C_RED}${C_BOLD}  Error: ${message}${C_RESET}"
    echo -e "${C_RED}$(repeat_char '━' "$TERMINAL_WIDTH")${C_RESET}"
    echo ""
}

# =============================================================================
# Stream Processing
# =============================================================================

process_stream() {
    local line
    local in_claude_box=false
    local accumulated_text=""
    local current_tool_name=""

    while IFS= read -r line; do
        # Skip empty lines
        [[ -z "$line" ]] && continue

        # Check for valid JSON
        if ! echo "$line" | jq -e . >/dev/null 2>&1; then
            # Non-JSON line (stderr or other output)
            debug_log "NON-JSON: $line"
            continue
        fi

        local event_type
        event_type=$(echo "$line" | jq -r '.type // empty')

        # Debug: log every event
        debug_log "EVENT: $event_type"
        debug_json "$line"

        case "$event_type" in
            system)
                # Initialization event - skip
                debug_log "  -> system event (skipped)"
                ;;

            assistant)
                # Full assistant message with content
                if [[ "$in_claude_box" == false ]]; then
                    display_claude_header
                    in_claude_box=true
                fi

                # Extract text from message.content array
                local text
                text=$(echo "$line" | jq -r '.message.content[] | select(.type=="text") | .text // empty' 2>/dev/null)
                if [[ -n "$text" ]]; then
                    # Print each line in the box
                    while IFS= read -r text_line; do
                        if [[ -n "$text_line" ]]; then
                            draw_box_line "$C_CLAUDE_BORDER" "$text_line"
                        fi
                    done <<< "$text"
                fi
                ;;

            content_block_delta)
                # Streaming delta (may not be used with current format)
                if [[ "$in_claude_box" == false ]]; then
                    display_claude_header
                    in_claude_box=true
                fi

                local delta_type text
                delta_type=$(echo "$line" | jq -r '.delta.type // empty')

                if [[ "$delta_type" == "text_delta" ]]; then
                    text=$(echo "$line" | jq -r '.delta.text // empty')
                    if [[ -n "$text" ]]; then
                        accumulated_text+="$text"
                        # Print when we hit a newline or have enough text
                        if [[ "$text" == *$'\n'* ]] || [[ ${#accumulated_text} -gt 60 ]]; then
                            while IFS= read -r text_line; do
                                if [[ -n "$text_line" ]]; then
                                    draw_box_line "$C_CLAUDE_BORDER" "$text_line"
                                fi
                            done <<< "$accumulated_text"
                            accumulated_text=""
                        fi
                    fi
                fi
                ;;

            tool_use)
                # Flush any remaining text
                if [[ -n "$accumulated_text" ]]; then
                    draw_box_line "$C_CLAUDE_BORDER" "$accumulated_text"
                    accumulated_text=""
                fi

                local tool_name tool_input
                tool_name=$(echo "$line" | jq -r '.name // empty')
                current_tool_name="$tool_name"
                debug_log "  -> tool_use: $tool_name"

                # Only display tool boxes if --show-tools is enabled
                if [[ "$SHOW_TOOLS" == true ]]; then
                    draw_box_empty "$C_CLAUDE_BORDER"
                    draw_tool_box_top "TOOL: $tool_name"

                    # Format input based on tool type
                    case "$tool_name" in
                        Bash)
                            local cmd
                            cmd=$(echo "$line" | jq -r '.input.command // empty')
                            draw_tool_box_line "${C_TOOL_INPUT}\$ ${cmd}${C_RESET}"
                            ;;
                        Read)
                            local path
                            path=$(echo "$line" | jq -r '.input.file_path // empty')
                            draw_tool_box_line "${C_TOOL_INPUT}file: ${path}${C_RESET}"
                            ;;
                        Edit)
                            local path
                            path=$(echo "$line" | jq -r '.input.file_path // empty')
                            draw_tool_box_line "${C_TOOL_INPUT}editing: ${path}${C_RESET}"
                            ;;
                        Write)
                            local path
                            path=$(echo "$line" | jq -r '.input.file_path // empty')
                            draw_tool_box_line "${C_TOOL_INPUT}writing: ${path}${C_RESET}"
                            ;;
                        Grep)
                            local pattern path
                            pattern=$(echo "$line" | jq -r '.input.pattern // empty')
                            path=$(echo "$line" | jq -r '.input.path // "."')
                            draw_tool_box_line "${C_TOOL_INPUT}/${pattern}/ in ${path}${C_RESET}"
                            ;;
                        Glob)
                            local pattern
                            pattern=$(echo "$line" | jq -r '.input.pattern // empty')
                            draw_tool_box_line "${C_TOOL_INPUT}pattern: ${pattern}${C_RESET}"
                            ;;
                        *)
                            # Generic display for other tools (including MCP tools)
                            local input_keys
                            input_keys=$(echo "$line" | jq -r '.input | keys | join(", ")' 2>/dev/null || echo "")
                            if [[ -n "$input_keys" ]]; then
                                draw_tool_box_line "${C_TOOL_INPUT}${input_keys}${C_RESET}"
                            fi
                            ;;
                    esac

                    draw_tool_box_bottom
                fi
                ;;

            tool_result)
                # Only display tool results if --show-tools is enabled
                if [[ "$SHOW_TOOLS" == true ]]; then
                    local content
                    content=$(echo "$line" | jq -r '.content // empty')

                    if [[ -n "$content" ]]; then
                        draw_box_empty "$C_CLAUDE_BORDER"
                        draw_tool_box_top "RESULT"

                        # Count lines and truncate if needed
                        local line_count
                        line_count=$(echo "$content" | wc -l)

                        if [[ $line_count -gt $MAX_RESULT_LINES ]]; then
                            echo "$content" | head -n "$MAX_RESULT_LINES" | while IFS= read -r result_line; do
                                draw_tool_box_line "${C_TOOL_OUTPUT}${result_line}${C_RESET}"
                            done
                            draw_tool_box_line "${C_DIM}... (${line_count} total lines)${C_RESET}"
                        else
                            echo "$content" | while IFS= read -r result_line; do
                                draw_tool_box_line "${C_TOOL_OUTPUT}${result_line}${C_RESET}"
                            done
                        fi

                        draw_tool_box_bottom
                    fi
                fi
                ;;

            content_block_stop)
                # Flush any remaining text
                if [[ -n "$accumulated_text" ]]; then
                    draw_box_line "$C_CLAUDE_BORDER" "$accumulated_text"
                    accumulated_text=""
                fi
                ;;

            message_stop)
                # Flush any remaining text and close box
                if [[ -n "$accumulated_text" ]]; then
                    draw_box_line "$C_CLAUDE_BORDER" "$accumulated_text"
                    accumulated_text=""
                fi
                if [[ "$in_claude_box" == true ]]; then
                    display_claude_footer
                    in_claude_box=false
                fi
                ;;

            result)
                # Final result event
                local status cost
                status=$(echo "$line" | jq -r '.subtype // empty')
                cost=$(echo "$line" | jq -r '.cost_usd // 0')

                # Close box if still open
                if [[ "$in_claude_box" == true ]]; then
                    if [[ -n "$accumulated_text" ]]; then
                        draw_box_line "$C_CLAUDE_BORDER" "$accumulated_text"
                        accumulated_text=""
                    fi
                    display_claude_footer
                    in_claude_box=false
                fi

                # Show cost if non-zero
                if [[ "$cost" != "0" && "$cost" != "null" && -n "$cost" ]]; then
                    echo -e "${C_DIM}  [Cost: \$${cost}]${C_RESET}"
                fi

                if [[ "$status" == "error" ]]; then
                    local error_msg
                    error_msg=$(echo "$line" | jq -r '.error // "Unknown error"')
                    display_error "$error_msg"
                    return 1
                fi
                ;;
        esac
    done

    # Ensure box is closed
    if [[ "$in_claude_box" == true ]]; then
        if [[ -n "$accumulated_text" ]]; then
            draw_box_line "$C_CLAUDE_BORDER" "$accumulated_text"
        fi
        display_claude_footer
    fi

    return 0
}

# =============================================================================
# Spinner (Claude Code style)
# =============================================================================

SPINNER_PID=""
SPINNER_CHARS="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Claude Code rotating status messages
SPINNER_MESSAGES=(
    "Thinking"
    "Pondering"
    "Reasoning"
    "Considering"
    "Analyzing"
    "Processing"
    "Contemplating"
    "Evaluating"
    "Reflecting"
)

# Claude Code purple/magenta branding
C_CLAUDE_SPINNER='\033[1;35m'  # Bold magenta

start_spinner() {
    (
        local spin_idx=0
        local msg_idx=0
        local spin_len=${#SPINNER_CHARS}
        local msg_len=${#SPINNER_MESSAGES[@]}
        local tick=0

        while true; do
            local char="${SPINNER_CHARS:$spin_idx:1}"
            local message="${SPINNER_MESSAGES[$msg_idx]}"
            printf "\r${C_CLAUDE_SPINNER}  %s %s...${C_RESET}   " "$char" "$message"

            spin_idx=$(( (spin_idx + 1) % spin_len ))
            tick=$((tick + 1))

            # Change message every ~20 ticks (2 seconds)
            if [[ $((tick % 20)) -eq 0 ]]; then
                msg_idx=$(( (msg_idx + 1) % msg_len ))
            fi

            sleep 0.1
        done
    ) &
    SPINNER_PID=$!
}

stop_spinner() {
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null
        SPINNER_PID=""
        printf "\r\033[K"  # Clear the spinner line
    fi
}

# =============================================================================
# Claude Execution
# =============================================================================

run_claude_prompt() {
    local prompt="$1"
    local output
    local exit_code

    debug_log "========================================"
    debug_log "PROMPT: $prompt"
    debug_log "========================================"

    # Start Claude Code style spinner
    start_spinner

    # Build claude command with optional debug flag
    local claude_cmd="claude -p --output-format stream-json --verbose --dangerously-skip-permissions"
    if [[ "$DEBUG_MODE" == true ]]; then
        claude_cmd="claude -p --output-format stream-json --verbose --debug --dangerously-skip-permissions"
    fi

    # Run Claude with streaming and capture output
    # Capture stderr separately for debug logs
    local stderr_file="/tmp/claude-stderr-$$.log"
    output=$($claude_cmd "$prompt" 2>"$stderr_file")
    exit_code=$?

    # Stop spinner
    stop_spinner

    # Process Claude's debug output if in debug mode
    if [[ "$DEBUG_MODE" == true ]] && [[ -f "$stderr_file" ]]; then
        local stderr_content
        stderr_content=$(cat "$stderr_file")
        if [[ -n "$stderr_content" ]]; then
            debug_log "=== Claude Debug Output ==="
            while IFS= read -r line; do
                debug_log "CLAUDE_DEBUG: $line"
            done <<< "$stderr_content"
            debug_log "=== End Claude Debug ==="
        fi
        rm -f "$stderr_file"
    fi

    debug_log "Claude exit code: $exit_code"
    debug_log "Output length: ${#output} chars"

    # Check if we got any output
    if [[ -z "$output" ]]; then
        echo -e "${C_RED}  [No output from Claude - exit code: $exit_code]${C_RESET}"
        debug_log "ERROR: No output from Claude"
        return 1
    fi

    # Process the output
    echo "$output" | process_stream
    local process_exit=${PIPESTATUS[1]}

    # Flush logs after each prompt
    flush_otel_logs

    # Return error if either Claude or processing failed
    if [[ $exit_code -ne 0 ]]; then
        return $exit_code
    fi
    return $process_exit
}

# =============================================================================
# Prompts File Parsing (preserved from original)
# =============================================================================

parse_prompts_file() {
    local file="$1"
    local current_desc=""
    local current_prompt=""
    local in_prompt=false

    DESCRIPTIONS=()
    PROMPTS=()

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^#\ description:\ (.+)$ ]]; then
            # Save previous prompt if exists
            if [[ -n "$current_prompt" ]]; then
                DESCRIPTIONS+=("$current_desc")
                PROMPTS+=("${current_prompt%$'\n'}")
            fi
            current_desc="${BASH_REMATCH[1]}"
            current_prompt=""
            in_prompt=true
        elif [[ "$line" == "---" ]]; then
            # Separator - save current prompt
            if [[ -n "$current_prompt" ]]; then
                DESCRIPTIONS+=("$current_desc")
                PROMPTS+=("${current_prompt%$'\n'}")
            fi
            current_desc=""
            current_prompt=""
            in_prompt=false
        elif [[ "$in_prompt" == true ]]; then
            # Accumulate prompt lines
            if [[ -n "$current_prompt" ]]; then
                current_prompt+=$'\n'
            fi
            current_prompt+="$line"
        fi
    done < "$file"

    # Save last prompt if file doesn't end with ---
    if [[ -n "$current_prompt" ]]; then
        DESCRIPTIONS+=("$current_desc")
        PROMPTS+=("${current_prompt%$'\n'}")
    fi
}

# =============================================================================
# Pacing Controls
# =============================================================================

wait_for_advance() {
    local current="$1"
    local total="$2"

    echo ""
    if [[ "$PACING_MODE" == "keypress" ]]; then
        echo -en "${C_DIM}[Press any key to continue... (${current}/${total})]${C_RESET}"
        read -rsn1
        echo ""
    else
        echo -en "${C_DIM}[Auto-advancing in ${AUTO_DELAY}s... (${current}/${total})]${C_RESET}"
        sleep "$AUTO_DELAY"
        echo ""
    fi
}

# =============================================================================
# Signal Handling
# =============================================================================

pause_handler() {
    stop_spinner  # Ensure spinner is stopped
    if [[ "$PAUSED" == false ]]; then
        PAUSED=true
        echo ""
        echo -e "${C_YELLOW}╭────────────────────────────────────────────────────────────╮${C_RESET}"
        echo -e "${C_YELLOW}│  PAUSED - Auto-play stopped                                │${C_RESET}"
        echo -e "${C_YELLOW}│  Press Enter to resume, or Ctrl+C again to exit           │${C_RESET}"
        echo -e "${C_YELLOW}╰────────────────────────────────────────────────────────────╯${C_RESET}"
        read -r
        PAUSED=false
    else
        echo ""
        echo -e "${C_GREEN}Exiting auto-play.${C_RESET}"
        exit 0
    fi
}

cleanup_on_exit() {
    stop_spinner
    flush_otel_logs  # Send any remaining buffered logs
}

trap pause_handler SIGINT
trap cleanup_on_exit EXIT

# =============================================================================
# Usage and Argument Parsing
# =============================================================================

show_usage() {
    echo "Usage: $0 [options] <scenario>"
    echo ""
    echo "Scenarios: issue, search, agile, jsm"
    echo ""
    echo "Options:"
    echo "  --auto-advance, -a    Auto-advance instead of waiting for keypress"
    echo "  --delay, -d <secs>    Delay between prompts in auto mode (default: 3)"
    echo "  --show-tools, -t      Show tool usage sub-boxes (off by default)"
    echo "  --debug               Log raw JSON to /tmp/autoplay-debug.log"
    echo "  --help, -h            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 issue                    # Run issue scenario, press key to advance"
    echo "  $0 --auto-advance search    # Auto-advance with 3s delay"
    echo "  $0 -a -d 5 agile            # Auto-advance with 5s delay"
    echo "  $0 -t issue                 # Show tool usage details"
    echo "  $0 --debug issue            # Debug mode with JSON logging"
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --auto-advance|-a)
                PACING_MODE="auto"
                shift
                ;;
            --delay|-d)
                AUTO_DELAY="$2"
                shift 2
                ;;
            --show-tools|-t)
                SHOW_TOOLS=true
                shift
                ;;
            --debug)
                DEBUG_MODE=true
                shift
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            -*)
                echo -e "${C_RED}Unknown option: $1${C_RESET}"
                show_usage
                exit 1
                ;;
            *)
                SCENARIO="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$SCENARIO" ]]; then
        echo -e "${C_RED}Error: No scenario specified${C_RESET}"
        show_usage
        exit 1
    fi
}

# =============================================================================
# Main Loop
# =============================================================================

run_scenario() {
    local prompts_file="${SCENARIOS_DIR}/${SCENARIO}.prompts"

    # Initialize debug logging if enabled
    init_debug

    if [[ ! -f "$prompts_file" ]]; then
        display_error "Scenario file not found: $prompts_file"
        exit 1
    fi

    # Parse prompts file
    parse_prompts_file "$prompts_file"

    local total=${#PROMPTS[@]}
    if [[ $total -eq 0 ]]; then
        display_error "No prompts found in scenario file"
        exit 1
    fi

    echo ""
    echo -e "${C_CYAN}Starting scenario: ${C_BOLD}${SCENARIO}${C_RESET}"
    echo -e "${C_CYAN}Total steps: ${total}${C_RESET}"
    echo -e "${C_CYAN}Mode: ${PACING_MODE}${C_RESET}"
    if [[ "$PACING_MODE" == "auto" ]]; then
        echo -e "${C_CYAN}Delay: ${AUTO_DELAY}s${C_RESET}"
    fi
    if [[ "$SHOW_TOOLS" == true ]]; then
        echo -e "${C_CYAN}Tools: enabled${C_RESET}"
    fi
    echo ""
    echo -e "${C_DIM}Press Ctrl+C to pause, Ctrl+C twice to exit${C_RESET}"

    # Initial wait
    if [[ "$PACING_MODE" == "keypress" ]]; then
        echo -en "${C_DIM}[Press any key to start...]${C_RESET}"
        read -rsn1
        echo ""
    else
        sleep 2
    fi

    # Run through prompts
    for ((i=0; i<total; i++)); do
        local step=$((i + 1))
        local desc="${DESCRIPTIONS[$i]}"
        local prompt="${PROMPTS[$i]}"

        get_terminal_width

        display_step_header "$step" "$total" "$desc"
        display_user_bubble "$prompt"

        if ! run_claude_prompt "$prompt"; then
            echo -e "${C_RED}Error occurred. Continue anyway? (y/N)${C_RESET}"
            read -rsn1 response
            if [[ "$response" != "y" && "$response" != "Y" ]]; then
                break
            fi
        fi

        # Wait for advancement (unless last step)
        if [[ $step -lt $total ]]; then
            wait_for_advance "$step" "$total"
        fi
    done

    display_completion

    # Wait before returning to menu so user can see final response
    echo ""
    echo -en "${C_DIM}[Press any key to return to menu...]${C_RESET}"
    read -rsn1
    echo ""
}

# =============================================================================
# Entry Point
# =============================================================================

main() {
    # Check for jq
    if ! command -v jq &>/dev/null; then
        echo -e "${C_RED}Error: jq is required but not installed${C_RESET}"
        exit 1
    fi

    # Check for claude
    if ! command -v claude &>/dev/null; then
        echo -e "${C_RED}Error: claude CLI is required but not installed${C_RESET}"
        exit 1
    fi

    parse_arguments "$@"
    get_terminal_width
    run_scenario
}

main "$@"
