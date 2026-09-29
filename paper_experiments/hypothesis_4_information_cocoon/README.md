# Study 4 - Emergence of information cocoons (AS2 paper Sec. 7.4) - NOT YET BUILT

**Status:** scaffold only. This is the one study that needs a large external dataset
plus a deep-learning recommender, so it is left as an explicit decision (see below).

## What the paper did

- **Population:** 10,000 users sampled from the mobile short-video dataset of
  Shang et al. (WWW 2025) - <https://github.com/tsinghua-fib-lab/ShortVideo_dataset>
  (10,000 users, 153,561 videos; the paper used 86,201 videos in 35 categories).
- **Agents:** `FinalCustomUserAgent` (custom `AgentBase`), **rule-based, no LLM per
  decision**: for each recommended video it looks up the video's category and runs
  user-specific decision code derived from the user's first 25 hours of logs.
- **Environment:** `VideoRecommendationEnv` (custom) with a **DIN** (Deep Interest
  Network) recommender pretrained on each user's first 5 sequences; loop per round:
  recommend -> category-diversity constraints + dedup -> agent watch decisions ->
  optional extra recommendations -> incremental model update.
- **Schedule:** 10 rounds (~6 months of consumption).
- **Metrics:** decline in viewing entropy (H1: all age groups), deeper cocoons for
  older users (H2), share of users in "deep information cocoons" by age group; plus
  three reranking interventions for users 50+ (Tail QuotaTransfer, Efficiency Boost,
  UnderServedBoost; each moves 30% of top-10-category exposure quota).

## What building it here requires

1. Download the interaction logs + user/video attributes from the dataset repo
   (the video-content embeddings/ASR are not needed); check sizes before downloading.
2. Install PyTorch in `.venv` for the DIN model (CPU is fine at this scale, but
   pretraining on 10k users takes a while).
3. Write `custom/envs/video_recommendation.py` (DIN + round loop + entropy logging)
   and `custom/agents/short_video_user_agent.py` (rule-based watch decisions).

LLM cost is negligible (agents are rule-based); the cost is download size, PyTorch,
and CPU time. Ask Claude to proceed once you are happy with those.
