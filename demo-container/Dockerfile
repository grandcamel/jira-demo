# =============================================================================
# JIRA Assistant Skills Demo Container
# =============================================================================
FROM grandcamel/claude-devcontainer:enhanced

USER root

# Install additional demo dependencies
RUN pip3 install --no-cache-dir --break-system-packages \
    jira-assistant-skills-lib>=0.1.5

# Copy MOTD (welcome message)
COPY motd /etc/motd
RUN chmod 644 /etc/motd

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Copy guided scenario documentation
COPY scenarios/ /workspace/scenarios/

# Create demo working directory
RUN mkdir -p /workspace/demo && chown devuser:node /workspace/demo

# Ensure cargo bin is in PATH for all shells
RUN echo 'export PATH="/usr/local/cargo/bin:$PATH"' >> /home/devuser/.bashrc && \
    echo 'export PATH="/usr/local/cargo/bin:$PATH"' >> /home/devuser/.profile

# Remove zoxide init from bashrc (not installed in this image)
RUN sed -i '/zoxide/d' /home/devuser/.bashrc 2>/dev/null || true

USER devuser

ENV JIRA_PROFILE=demo
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ENV DEMO_SESSION=true
ENV PATH="/usr/local/cargo/bin:${PATH}"

WORKDIR /workspace/demo

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash", "-l"]
