# AI settings

- Model: ollama · gigalab-local, with a second provider on timeout or 429. One model for every AI feature.
- Whose key pays: Your key (you bill the customer).
- Called from: Your server, keys in .env.
- Keys live only in .env on the server.
- AI budget per customer: RM1,000.00 a month.

## What each customer’s account controls
- A monthly AI budget per customer, with an alert at 80%
- AI usage and cost per customer on a dashboard
- Change the model or provider in settings, not in code

## AI features and their models
- AI MESSAGE PARSER (summarise): gigalab-local, about 300 uses per customer a month
- Recipe & Ingredient Costing (summarise): gigalab-local, about 300 uses per customer a month
