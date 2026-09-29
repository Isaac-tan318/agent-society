---
name: self-reference-task
description: REQUIRED in this experiment. Complete both phases of the Self-Reference Effect memory task in SelfReferenceEffectEnv (encoding ratings of traits for self/friend/other, then old/new recognition with remember/know), then finish.
---

# Self-Reference Effect task (Qi et al., 2025)

**Phase 1 - Encoding.** Each trait adjective (Chinese) comes with an identity: **self**, **friend** or
**other** (a familiar other person). Rate how well the trait describes that person from **1 (not at all)
to 5 (very well)**. Read each trait carefully - you will later be tested on it.

**Phase 2 - Recognition.** For each trait shown, judge whether it appeared in Phase 1 (**"old"**) or not
(**"new"**). For "old" judgments also say whether you consciously **remember** seeing it (`remember`) or it
only feels familiar (`know`). Rely on your own memory of Phase 1 - do not look the encoding list up.

## Procedure (use the `ask_env` action)

**Always put your answers in `variables`** (never type the numbers into the instruction text), and replace every `<...>` placeholder with your own value.

1. `ask_env` (readonly=true): "Call get_encoding_status() for my agent id and report the remaining traits
   with their identities."
2. Submit ratings in batches of up to 20 per `ask_env` call (readonly=false), instruction "For agent_id
   in ctx['variables'], call submit_encoding_rating() once for each entry of ctx['variables']['ratings']
   using its trait, identity and rating." and variables {"agent_id": <your id>, "ratings":
   [{"trait": "<trait>", "identity": "<self|friend|other>", "rating": <1-5>}, ...]}.
3. When encoding is complete: `ask_env` (readonly=true): "Call get_recognition_status() for my agent id
   and report the remaining traits."
4. Submit judgments in batches of up to 20 (readonly=false), instruction "For agent_id in
   ctx['variables'], call submit_recognition() once for each entry of ctx['variables']['judgments']
   using its trait, judge_type and rk_type." and variables {"agent_id": <your id>, "judgments":
   [{"trait": "<trait>", "judge_type": "<old|new>", "rk_type": "<remember|know or null if new>"}, ...]}.
5. When both phases are complete, call `finish`.
