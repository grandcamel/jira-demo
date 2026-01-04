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

# Display welcome message
clear
cat /etc/motd

# Install JIRA Assistant Skills plugin (if not already installed)
echo -e "${CYAN}Setting up plugins...${NC}"
if ! claude plugin list 2>/dev/null | grep -q "jira-assistant-skills"; then
    claude plugin marketplace add /opt/jira-assistant-skills >/dev/null 2>&1
    claude plugin install jira-assistant-skills@jira-assistant-skills --scope user >/dev/null 2>&1
    echo -e "  ${GREEN}✓${NC} JIRA Assistant Skills installed"
else
    echo -e "  ${GREEN}✓${NC} JIRA Assistant Skills ready"
fi
echo ""

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

echo -e "${GREEN}Ready! Type 'claude' followed by your request, or try the examples above.${NC}"
echo ""

# Start the shell
exec "$@"
