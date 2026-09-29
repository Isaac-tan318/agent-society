---
name: self-enhancement-task
description: REQUIRED in this experiment. Complete the Self-Enhancement task in SelfEnhancementEnv - rate yourself against the average Tsinghua University student on 8 dimensions with a reverse-coded percentile scale - then finish.
---

# Self-Enhancement task (Qi et al., 2025)

Compare yourself with the average Tsinghua University student on each of 8 dimensions:
**INTELLIGENCE, COOPERATION, APPEARANCE, MORALITY, SOCIABILITY, HEALTH, HONESTY, GENEROSITY**.

Give a percentile on a **reverse-coded scale**: **0 = you are the best of all students**,
**50 = exactly average (the median student)**, **100 = you are the worst of all students**.
Answer honestly as yourself, based on your own profile.

## Procedure (use the `ask_env` action)

**Always put your answers in `variables`** (never type the numbers into the instruction text), and replace every `<...>` placeholder with your own value.

1. `ask_env` (readonly=true): "Call get_my_rankings() for my agent id and report completed and remaining dimensions."
2. Submit ALL remaining dimensions in ONE `ask_env` call with readonly=false, instruction "For agent_id
   in ctx['variables'], call submit_ranking() once for each dimension in ctx['variables']['percentiles']
   with that percentile." and variables {"agent_id": <your id>, "percentiles": {"INTELLIGENCE": <0-100>,
   "COOPERATION": <0-100>, ..., "GENEROSITY": <0-100>}} (integers on the scale above).
3. Check again; when all 8 are completed, call `finish`. Never resubmit a completed dimension.
