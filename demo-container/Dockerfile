# =============================================================================
# JIRA Assistant Skills Demo Container
# =============================================================================
# Extends claude-devcontainer:enhanced with JIRA skills pre-configured
# for live demo sessions.
#
# Build: docker build -t jira-demo-container:latest .
# Run:   docker run -it --rm -e JIRA_API_TOKEN=... jira-demo-container:latest
# =============================================================================

FROM grandcamel/claude-devcontainer:enhanced

# Switch to root for installation
USER root

# Install additional demo dependencies
RUN pip3 install --no-cache-dir --break-system-packages \
    jira-assistant-skills-lib>=0.1.5

# Copy MOTD (welcome message)
COPY motd /etc/motd

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy guided scenario documentation
COPY scenarios/ /workspace/scenarios/

# Create demo working directory
RUN mkdir -p /workspace/demo && chown devuser:devuser /workspace/demo

# Switch back to non-root user
USER devuser

# Set demo-specific environment
ENV JIRA_PROFILE=demo
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ENV DEMO_SESSION=true

# Working directory for demo
WORKDIR /workspace/demo

# Custom entrypoint with session management
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash", "-l"]
