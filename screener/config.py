"""Tunable constants for the screening job. Parent-facing settings live in rules.yaml."""

from pathlib import Path

# The Claude model that screens videos. Change it here and nowhere else.
MODEL_ID = "claude-haiku-5-5"

# Most new videos sent to the AI in one run. Controls Anthropic cost.
MAX_SCREENED_PER_RUN = 40

# YouTube quota controls. playlistItems.list and videos.list cost 1 unit per
# call; search.list costs 100. The free daily quota is 10,000 units.
MAX_UPLOAD_PAGES_PER_CHANNEL = 3      # 50 videos per page, newest first
MAX_NEW_IDS_PER_CHANNEL = 50          # unseen videos considered per channel per run
MAX_SEARCHES_PER_RUN = 1
SEARCH_RESULTS_PER_QUERY = 25

# Shorts can run up to three minutes. Videos at or under this length get an
# extra check against youtube.com before they are sent to the AI.
SHORTS_MAX_SECONDS = 185

# Transcript handling. The excerpt length bounds the AI input size per video.
TRANSCRIPT_MAX_CHARS = 12000
TRANSCRIPT_FAILURES_BEFORE_GIVING_UP = 3
DESCRIPTION_MAX_CHARS = 2000

# Stop screening after this many AI calls in a row fail for transient reasons.
AI_FAILURES_BEFORE_GIVING_UP = 3

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "rules.yaml"
DATA_DIR = ROOT / "data"
APPROVED_PATH = DATA_DIR / "approved.json"
REJECTED_PATH = DATA_DIR / "rejected.json"
LINEUP_PATH = DATA_DIR / "lineup.json"
