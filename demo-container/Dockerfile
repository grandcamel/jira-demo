# =============================================================================
# JIRA Assistant Skills Demo Container
# =============================================================================
FROM grandcamel/claude-devcontainer:enhanced

USER root

# Note: jira-assistant-skills CLI is installed at runtime in entrypoint.sh
# to pick up latest updates without rebuilding the image

# Install glow for terminal markdown rendering
RUN curl -fsSL -o /tmp/glow.tar.gz \
    https://github.com/charmbracelet/glow/releases/download/v2.0.0/glow_2.0.0_Linux_x86_64.tar.gz && \
    tar -xzf /tmp/glow.tar.gz -C /tmp && \
    mv /tmp/glow_2.0.0_Linux_x86_64/glow /usr/local/bin/glow && \
    chmod +x /usr/local/bin/glow && \
    rm -rf /tmp/glow.tar.gz /tmp/glow_2.0.0_Linux_x86_64

# Copy MOTD (welcome message)
COPY motd /etc/motd
RUN chmod 644 /etc/motd

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

# Copy guided scenario documentation and prompts files
COPY scenarios/ /workspace/scenarios/
RUN chown -R devuser:node /workspace/scenarios

# Copy auto-play script
COPY autoplay.sh /workspace/autoplay.sh
RUN chmod 755 /workspace/autoplay.sh && chown devuser:node /workspace/autoplay.sh

# Create demo working directory
RUN mkdir -p /workspace/demo && chown devuser:node /workspace/demo

# Copy Claude settings (bypass permission prompts for demo)
COPY settings.json /home/devuser/.claude/settings.json
RUN chown devuser:node /home/devuser/.claude/settings.json

# Ensure cargo bin is in PATH for all shells
RUN echo 'export PATH="/usr/local/cargo/bin:$PATH"' >> /home/devuser/.bashrc && \
    echo 'export PATH="/usr/local/cargo/bin:$PATH"' >> /home/devuser/.profile

# Remove zoxide references from bashrc (not installed in this image)
RUN sed -i '/zoxide/d; /alias cd="z"/d' /home/devuser/.bashrc 2>/dev/null || true

USER devuser

ENV JIRA_PROFILE=demo
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
ENV DEMO_SESSION=true
ENV PATH="/usr/local/cargo/bin:${PATH}"

WORKDIR /workspace/demo

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash", "-l"]
