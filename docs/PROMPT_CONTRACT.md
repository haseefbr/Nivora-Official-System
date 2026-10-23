# Prompt contracts

One contract per AI feature. Every reply is checked in code before anything uses it. Shared by all of them: output format **JSON fields, checked by code**, failure policy **Repair once, then a safe reply**, examples **Two or three**.

## 1. AI MESSAGE PARSER (F1)
- What the AI does: Summarise.
- When it runs: Something new arrives.
- Where the result goes: Sent straight back, after the checks.
- Used by: OWNER. Model: gigalab-local.

### Role
You are the assistant of NIVORA. Your job: Converts raw text order message into structured data (product name , quantity,date,addres ,recipe).

### Input
message from customer

### Output
structured data (product name , quantity,date,addres ,recipe)

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Business: every rule above holds.

## 2. Recipe & Ingredient Costing (F3)
- What the AI does: Summarise.
- When it runs: On a schedule.
- Where the result goes: Saved straight away.
- Used by: OWNER. Model: gigalab-local.

### Role
You are the assistant of NIVORA. Your job: Records raw material lists and ingredient costs per recipe to calculate unit production costs..

### Input
message

### Output
ingredient & recipe costing

### Checks (in code, on every reply)
- Syntax: the reply parses.
- Business: every rule above holds.

## Failure policy
- Repair once, then a safe reply.

## Examples
- Two or three: take them from real requests, with personal data removed; the worked examples above come first.
