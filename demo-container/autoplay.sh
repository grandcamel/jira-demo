#!/bin/bash
# =============================================================================
# JIRA Demo Auto-Play Script
# =============================================================================
# Automatically executes scenario prompts through Claude with step-by-step
# progress display. User can pause with Ctrl+C to take over manually.
#
# Usage: autoplay.sh <scenario-name>
# Example: autoplay.sh issue
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Configuration
DELAY_BETWEEN_STEPS=15
PROMPT_TIMEOUT=120

# Scenario name from argument
SCENARIO="${1:-}"

if [ -z "$SCENARIO" ]; then
    echo -e "${RED}Error: No scenario specified${NC}"
    echo "Usage: autoplay.sh <scenario-name>"
    echo "Available: issue, search, agile, jsm"
    exit 1
fi

PROMPTS_FILE="/workspace/scenarios/${SCENARIO}.prompts"

if [ ! -f "$PROMPTS_FILE" ]; then
    echo -e "${RED}Error: Prompts file not found: $PROMPTS_FILE${NC}"
    exit 1
fi

# Parse prompts file into arrays
declare -a DESCRIPTIONS
declare -a PROMPTS

parse_prompts_file() {
    local current_desc=""
    local current_prompt=""
    local in_prompt=false

    while IFS= read -r line || [ -n "$line" ]; do
        # Check for description comment
        if [[ "$line" =~ ^#\ description:\ (.+)$ ]]; then
            current_desc="${BASH_REMATCH[1]}"
            in_prompt=true
            current_prompt=""
        # Check for separator
        elif [[ "$line" == "---" ]]; then
            if [ -n "$current_prompt" ]; then
                DESCRIPTIONS+=("$current_desc")
                PROMPTS+=("$current_prompt")
            fi
            in_prompt=false
            current_desc=""
            current_prompt=""
        # Accumulate prompt text
        elif $in_prompt && [ -n "$line" ]; then
            if [ -n "$current_prompt" ]; then
                current_prompt="$current_prompt
$line"
            else
                current_prompt="$line"
            fi
        fi
    done < "$PROMPTS_FILE"

    # Handle last prompt if file doesn't end with ---
    if [ -n "$current_prompt" ]; then
        DESCRIPTIONS+=("$current_desc")
        PROMPTS+=("$current_prompt")
    fi
}

# Parse the prompts file
parse_prompts_file

TOTAL_STEPS=${#PROMPTS[@]}

if [ "$TOTAL_STEPS" -eq 0 ]; then
    echo -e "${RED}Error: No prompts found in $PROMPTS_FILE${NC}"
    exit 1
fi

# Error detection patterns
ERROR_PATTERNS="Error:|error:|Failed|failed|not found|denied|permission|Exception|Invalid"

# Flag for pause
PAUSED=false

# Trap Ctrl+C for pause
pause_handler() {
    PAUSED=true
    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  Auto-play PAUSED - You now have control                      ║${NC}"
    echo -e "${YELLOW}║  Continue typing prompts manually or type 'exit' to quit     ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

trap pause_handler SIGINT

# Display header
clear
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           AUTO-PLAY: ${BOLD}${SCENARIO^^}${NC}${CYAN} SCENARIO                      ║${NC}"
echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║${NC}  Steps: $TOTAL_STEPS                                                      ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  Press ${YELLOW}Ctrl+C${NC} at any time to pause and take over            ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Starting Claude...${NC}"
echo ""
sleep 2

# Create a temporary expect script for automation
EXPECT_SCRIPT=$(mktemp)
cat > "$EXPECT_SCRIPT" << 'EXPECT_EOF'
#!/usr/bin/expect -f

# Get arguments
set timeout [lindex $argv 0]
set total [lindex $argv 1]
# Remaining args are alternating descriptions and prompts

# Start Claude
spawn claude --dangerously-skip-permissions

# Wait for initial prompt - Claude Code shows "> " in a formatted box
# Look for the prompt line pattern
expect {
    -re {>\s+\r?\n.*───} { }
    -re {>\s*$} { }
    "bypass permissions" { }
    timeout { puts "Timeout waiting for Claude"; exit 1 }
}

# Small delay to ensure Claude is fully ready
sleep 2

# Process each step
set step 1
for {set i 2} {$i < [llength $argv]} {incr i 2} {
    set desc [lindex $argv $i]
    set prompt [lindex $argv [expr {$i + 1}]]

    # Display step header
    puts "\n\033\[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033\[0m"
    puts "\033\[1;33mStep $step/$total:\033\[0m \033\[1m$desc\033\[0m"
    puts "\033\[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033\[0m\n"

    # Send the prompt - type it out, pause, then press Enter
    send "$prompt"
    sleep 1
    send "\r"

    # Wait for Claude to finish (prompt reappears)
    # Claude Code shows "> " when ready for input
    expect {
        -re {>\s+\r?\n.*───} {
            # Check for errors in output
            set output $expect_out(buffer)
            if {[regexp -nocase {Error:|Failed|not found|denied|permission denied|Exception} $output]} {
                puts "\n\033\[1;31m⚠ Error detected - stopping auto-play\033\[0m"
                puts "\033\[0;33mYou can continue manually or type 'exit' to quit\033\[0m\n"
                interact
                exit 0
            }
        }
        "bypass permissions" {
            # Claude is ready
        }
        timeout {
            puts "\n\033\[1;33m⚠ Timeout - continuing to next step\033\[0m\n"
        }
    }

    # Delay before next step (unless last step)
    if {$step < $total} {
        sleep 15
    }

    incr step
}

# All steps complete
puts "\n\033\[1;32m╔══════════════════════════════════════════════════════════════╗\033\[0m"
puts "\033\[1;32m║  ✓ Auto-play complete! You can continue exploring.           ║\033\[0m"
puts "\033\[1;32m║    Type 'exit' when done or try other commands.              ║\033\[0m"
puts "\033\[1;32m╚══════════════════════════════════════════════════════════════╝\033\[0m\n"

# Hand over control to user
interact
EXPECT_EOF

chmod +x "$EXPECT_SCRIPT"

# Build arguments for expect script
EXPECT_ARGS=("$PROMPT_TIMEOUT" "$TOTAL_STEPS")
for ((i=0; i<TOTAL_STEPS; i++)); do
    EXPECT_ARGS+=("${DESCRIPTIONS[$i]}" "${PROMPTS[$i]}")
done

# Run the expect script
expect "$EXPECT_SCRIPT" "${EXPECT_ARGS[@]}"
EXIT_CODE=$?

# Cleanup
rm -f "$EXPECT_SCRIPT"

exit $EXIT_CODE
