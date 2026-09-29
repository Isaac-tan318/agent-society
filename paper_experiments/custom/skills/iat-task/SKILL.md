---
name: iat-task
description: REQUIRED in this experiment. Complete every trial of the Implicit Association Test of self-esteem in ImplicitAssociationTestEnv (categorize each stimulus with key z = left or m = right and report a reaction time), then finish.
---

# Implicit Association Test (IAT) of self-esteem (Qi et al., 2025)

The test has many short categorization trials in blocks (identity practice, valence practice,
combined blocks, reversed identity practice, reversed combined blocks). Each trial shows a **stimulus**
word (Chinese) and two category labels: one on the **LEFT (key "z")** and one on the **RIGHT (key "m")**.
Press the key of the side whose category the stimulus belongs to, as quickly and accurately as a person
would. Also report your **reaction time in seconds** (people typically take about 0.4-1.5 s; unfamiliar
or conflicting pairings take longer).

## Procedure per trial (use the `ask_env` action)

**Always put your answers in `variables`** (never type the numbers into the instruction text), and replace every `<...>` placeholder with your own value.

1. `ask_env` (readonly=true): "Call get_next_trial() for my agent id and report the trial id, stimulus,
   left label, right label and block."
2. Decide the key ("z" or "m") and your reaction time.
3. `ask_env` (readonly=false), instruction "Call submit_trial_response() with agent_id, trial_id,
   key_press and rt from ctx['variables']." and variables {"agent_id": <your id>, "trial_id": <id>,
   "key_press": "<z or m>", "rt": <seconds>}.

Repeat for as many trials as you can within each step. When get_next_trial reports that no trials remain,
call `finish`. Never skip or resubmit a trial.
