"""Shared config for the iaedu.pt agent (used by multiple routers)."""

import os

AI_API_URL = os.getenv(
    "AI_API_URL",
    "https://api.iaedu.pt/agent-chat//api/v1/agent/cmamvd3n40000c801qeacoad2/stream",
)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_CHANNEL_ID = os.getenv("AI_CHANNEL_ID", "cmnauzuoxjik3hv01gjna24hw")
