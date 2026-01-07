#!/bin/bash
# =============================================================================
# JIRA Demo Container Entrypoint
# =============================================================================
# Displays welcome message, verifies connections, and starts session timer.
# =============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Session timeout (default: 60 minutes)
SESSION_TIMEOUT_MINUTES="${SESSION_TIMEOUT_MINUTES:-60}"
SESSION_TIMEOUT_SECONDS=$((SESSION_TIMEOUT_MINUTES * 60))

# Copy Claude config from mounted source (allows Claude to write to it)
if [ -f /tmp/.claude.json.source ]; then
    cp /tmp/.claude.json.source /home/devuser/.claude/.claude.json
    chmod 644 /home/devuser/.claude/.claude.json
fi

# Display welcome message
clear
cat /etc/motd

# Verify Claude credentials
echo -e "${CYAN}Checking connections...${NC}"

if [ -f /home/devuser/.claude/.credentials.json ]; then
    echo -e "  ${GREEN}✓${NC} Claude credentials loaded"
else
    echo -e "  ${YELLOW}⚠${NC} Claude credentials not found (OAuth may prompt)"
fi

# Verify JIRA connection
if [ -n "$JIRA_API_TOKEN" ] && [ -n "$JIRA_EMAIL" ] && [ -n "$JIRA_SITE_URL" ]; then
    echo -e "  ${GREEN}✓${NC} JIRA credentials configured"

    # Quick connectivity test
    if curl -sf -u "${JIRA_EMAIL}:${JIRA_API_TOKEN}" \
        "${JIRA_SITE_URL}/rest/api/3/myself" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Connected to $(echo $JIRA_SITE_URL | sed 's|https://||')"
    else
        echo -e "  ${YELLOW}⚠${NC} JIRA connection test failed (credentials may be invalid)"
    fi
else
    echo -e "  ${RED}✗${NC} JIRA credentials not configured"
fi

echo ""
echo -e "${CYAN}Session Info:${NC}"
echo -e "  Duration: ${SESSION_TIMEOUT_MINUTES} minutes"
echo -e "  Started:  $(date '+%H:%M:%S %Z')"
echo ""

# Start session timer in background
(
    # Warning at 5 minutes remaining
    warning_time=$((SESSION_TIMEOUT_SECONDS - 300))
    if [ $warning_time -gt 0 ]; then
        sleep $warning_time
        echo ""
        echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ⏰ 5 MINUTES REMAINING - Your session will end soon          ║${NC}"
        echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        sleep 300
    else
        sleep $SESSION_TIMEOUT_SECONDS
    fi

    # Session timeout
    echo ""
    echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ⏱️  SESSION TIMEOUT - Your 1-hour demo has ended             ║${NC}"
    echo -e "${RED}║                                                               ║${NC}"
    echo -e "${RED}║  Thank you for trying JIRA Assistant Skills!                  ║${NC}"
    echo -e "${RED}║  Visit: github.com/grandcamel/jira-assistant-skills           ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Give user a moment to see the message, then exit
    sleep 5
    kill -TERM $$ 2>/dev/null
) &

# Trap to clean up timer on exit
cleanup() {
    # Kill all background jobs
    jobs -p | xargs -r kill 2>/dev/null
}
trap cleanup EXIT

# Install JIRA Assistant Skills CLI from PyPI
echo -e "${CYAN}Installing JIRA Assistant Skills...${NC}"
if pip install --quiet --no-cache-dir jira-assistant-skills 2>/dev/null; then
    CLI_VERSION=$(pip show jira-assistant-skills 2>/dev/null | grep Version | cut -d' ' -f2)
    echo -e "  ${GREEN}✓${NC} jira CLI v${CLI_VERSION} installed"
else
    echo -e "  ${YELLOW}⚠${NC} CLI installation failed"
fi

# Install JIRA Assistant Skills plugin from marketplace (clear all plugin cache first)
rm -rf ~/.claude/plugins 2>/dev/null || true
# Use main branch to get latest (v2.2.0 tag has invalid assistant_skills key)
claude plugin marketplace add https://github.com/grandcamel/jira-assistant-skills.git#main >/dev/null 2>&1 || true
claude plugin install jira-assistant-skills@jira-assistant-skills --scope user >/dev/null 2>&1 || true
# Verify installation
INSTALLED_VERSION=$(cat ~/.claude/plugins/cache/*/jira-assistant-skills/*/plugin.json 2>/dev/null | jq -r '.version' | head -1)
if [ -n "$INSTALLED_VERSION" ]; then
    echo -e "  ${GREEN}✓${NC} Claude plugin v${INSTALLED_VERSION} ready"
else
    echo -e "  ${YELLOW}⚠${NC} Plugin installation failed (will retry on first use)"
fi
echo ""
echo -e "${YELLOW}Press Enter to continue...${NC}"
read -r

# =============================================================================
# Interactive Startup Menu
# =============================================================================

show_menu() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                    JIRA Assistant Demo                        ║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  ${GREEN}1)${NC} View Scenarios                                            ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  ${GREEN}2)${NC} Start Claude (interactive mode)                          ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  ${GREEN}3)${NC} Start Bash Shell                                         ${CYAN}║${NC}"
    if [ "${ENABLE_AUTOPLAY:-false}" = "true" ]; then
        echo -e "${CYAN}║${NC}  ${GREEN}4)${NC} Auto-play Scenario ${YELLOW}(watch a live demo)${NC}                   ${CYAN}║${NC}"
    fi
    echo -e "${CYAN}║${NC}  ${GREEN}q)${NC} Exit                                                     ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

show_scenarios_menu() {
    echo ""
    echo -e "${CYAN}Available Scenarios:${NC}"
    echo -e "  ${GREEN}1)${NC} Issue Management  - Create, update, transition issues"
    echo -e "  ${GREEN}2)${NC} Search & JQL      - Find issues, build queries"
    echo -e "  ${GREEN}3)${NC} Agile Workflows   - Sprints, epics, story points"
    echo -e "  ${GREEN}4)${NC} Service Desk      - JSM requests, SLAs, queues"
    echo -e "  ${GREEN}5)${NC} Observability     - Explore Grafana dashboards"
    echo -e "  ${GREEN}b)${NC} Back to main menu"
    echo ""
}

view_scenario() {
    local file="$1"
    if [ -f "$file" ]; then
        clear
        # Use glow for beautiful markdown rendering
        glow -p "$file"
    else
        echo -e "${RED}Scenario file not found: $file${NC}"
        sleep 2
    fi
}

scenarios_loop() {
    while true; do
        clear
        cat /etc/motd
        show_scenarios_menu
        read -rp "Select scenario: " choice
        case $choice in
            1) view_scenario "/workspace/scenarios/issue.md" ;;
            2) view_scenario "/workspace/scenarios/search.md" ;;
            3) view_scenario "/workspace/scenarios/agile.md" ;;
            4) view_scenario "/workspace/scenarios/jsm.md" ;;
            5) view_scenario "/workspace/scenarios/observability.md" ;;
            b|B) return ;;
            *) echo -e "${YELLOW}Invalid option${NC}"; sleep 1 ;;
        esac
    done
}

show_autoplay_menu() {
    echo ""
    echo -e "${CYAN}Auto-play Scenarios:${NC}"
    echo -e "  ${GREEN}1)${NC} Issue Management  - Create, update, transition issues"
    echo -e "  ${GREEN}2)${NC} Search & JQL      - Find issues using natural language"
    echo -e "  ${GREEN}3)${NC} Agile Workflows   - Sprints, epics, story points"
    echo -e "  ${GREEN}4)${NC} Service Desk      - JSM requests and comments"
    echo -e "  ${GREEN}b)${NC} Back to main menu"
    echo ""
    echo -e "${YELLOW}Tip: Press Ctrl+C during auto-play to pause and take over${NC}"
    echo ""
}

autoplay_loop() {
    while true; do
        clear
        cat /etc/motd
        show_autoplay_menu
        read -rp "Select scenario to auto-play: " choice
        case $choice in
            1) /workspace/autoplay.sh issue || true ;;
            2) /workspace/autoplay.sh search || true ;;
            3) /workspace/autoplay.sh agile || true ;;
            4) /workspace/autoplay.sh jsm || true ;;
            b|B) return ;;
            *) echo -e "${YELLOW}Invalid option${NC}"; sleep 1 ;;
        esac
    done
}

main_menu_loop() {
    while true; do
        clear
        cat /etc/motd
        show_menu
        read -rp "Select option: " choice
        case $choice in
            1)
                scenarios_loop
                ;;
            2)
                clear
                echo -e "${GREEN}Starting Claude in interactive mode...${NC}"
                echo -e "${YELLOW}Tip: Type 'exit' or press Ctrl+C to return to menu${NC}"
                echo ""
                claude --dangerously-skip-permissions "Hello, JIRA!" || true
                ;;
            3)
                clear
                echo -e "${GREEN}Starting Bash shell...${NC}"
                echo -e "${YELLOW}Tip: Type 'exit' to return to menu${NC}"
                echo -e "${YELLOW}     Run 'claude --dangerously-skip-permissions' to start Claude${NC}"
                echo ""
                /bin/bash -l || true
                ;;
            4)
                if [ "${ENABLE_AUTOPLAY:-false}" = "true" ]; then
                    autoplay_loop
                else
                    echo -e "${YELLOW}Invalid option${NC}"
                    sleep 1
                fi
                ;;
            q|Q)
                echo -e "${GREEN}Goodbye! Thanks for trying JIRA Assistant Skills.${NC}"
                exit 0
                ;;
            *)
                echo -e "${YELLOW}Invalid option${NC}"
                sleep 1
                ;;
        esac
    done
}

# Start the interactive menu
main_menu_loop
