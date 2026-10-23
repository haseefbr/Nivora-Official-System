# State

Store: **SQLite**.

## Limits
- AI calls per person: 10 a minute.
- AI calls per customer: 56 a day (the plan limit; higher plans raise it).

## What is kept from each AI call
- (not chosen yet). Never in the logs.

## Keys (every key starts with the tenant)
| Key | What | Expires |
|---|---|---|
| `nivora:{tenant}:{user}:rl:{minute}` | a person's AI calls this minute (limit 10) | 60 seconds |
| `nivora:{tenant}:rl:{day}` | the customer's AI calls today (limit 56) | 1 day |

## Rules
- Count with one atomic step (INCR with EXPIRE in a Lua script, as in Module 6), never a separate GET and SET.
- Over a limit: refuse with a clear message and when to retry.
