---
name: endowment-effect-task
description: REQUIRED in this experiment. Complete the Endowment Effect pricing task in EndowmentEffectEnv (selling price WTA and buying price WTP for pen, plate, glass and doll), then finish.
---

# Endowment Effect pricing task (Qi et al., 2025)

You are a participant in a pricing study. For each of four everyday items - **pen, plate, glass, doll** -
give two prices in Chinese yuan (CNY), each between 0 and 100:

- **WTA (willingness to accept):** imagine you OWN this item. What is the lowest price at which you would sell it?
- **WTP (willingness to pay):** imagine you do NOT own this item. What is the highest price you would pay to buy it?

Answer as yourself, from your own profile, tastes and judgment. There are no right or wrong answers.

## Procedure (use the `ask_env` action)

**Always put your answers in `variables`** (never type the numbers into the instruction text), and replace every `<...>` placeholder with your own value.

1. Check progress with `ask_env` (readonly=true), instruction: "Call get_my_evaluations() for my agent id
   and report which items are completed and which remain."
2. Decide your prices, then submit ALL remaining items in ONE `ask_env` call with readonly=false,
   instruction "For agent_id in ctx['variables'], call submit_wta_wtp() once for each item in
   ctx['variables']['prices'] with that item's wta and wtp." and
   variables {"agent_id": <your id>, "prices": {"pen": {"wta": <number>, "wtp": <number>},
   "plate": {...}, "glass": {...}, "doll": {...}}} (include only the remaining items).
3. Check progress again. When all four items are completed, call `finish`. Never resubmit a completed item.
