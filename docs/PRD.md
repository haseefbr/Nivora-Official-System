# Product requirements

**NIVORA**: AI order & Profit Assistant yg menukarkan mesej tempahan , which is dia mesej dalam system tu ,kepada pelan pengeluaran dan pengiraan kos untuk penjual makanan di malaysia

## Customer and problem
- Who pays: Penjual kuih, peniaga, business owner
- Problem: business owner does not need to do their own Business financial projections / Business calculations.
- Today: By taking the recipe n business calculation by their own
- How often: 300 tasks per customer a month
- What it costs them now: about RM300.00 a month
- Languages: Both; channel: A web app or web chat

## Who uses it
- OWNER: RUNS THE BUSINESS AND PAY

## AI fit
- Good fit.
- ✓ The task repeats: you can write test cases for it.
- ✓ Code can check the answer (Module 2).
- ✓ A mistake costs little.
- ✓ 300 tasks per customer a month: enough to be worth paying for.
- ✓ The problem costs them about RM300.00 a month: your price must sit well below that.

## Version 1 does
- AI MESSAGE PARSER: Converts raw text order message into structured data (product name , quantity,date,addres ,recipe) (AI, checked by code before anyone sees it)
- Order Management Dashboard: Display clean overview of all active orders, payment statuses and delivery dates in one places
- Recipe & Ingredient Costing: Records raw material lists and ingredient costs per recipe to calculate unit production costs. (AI, checked by code before anyone sees it)
- Production Planning: Aggregates all orders for a specific date to calculate the total batch quantities required for cooking/baking.
- Automatic Grocery List: Automatically generates a raw material shopping list based on daily or weekly production plans
- Profit & Loss Calculator: Calculates estimated net profit per order after deducting raw material costs.
- MESSAGE BOX: WHERE CUSTOMER CAN CHHAT OWNER STATING THEIR ORDERS 
- Each customer’s data is kept apart; people sign in, and each role may do only what docs/AUTH.md allows.

## Later
- Customer Database (should)
- Payment Status Tracker (should)

## Version 1 does not do
- Anything not listed above.

## Success
- The release gate passes: all critical cases pass, 90% overall.
- The quality targets in docs/QUALITY.md pass.
- A task costs about $0 in tokens.
- 3 paying customers in the first three months.

## Never
- Never send anything outside without a person's approval
- never invent a price, a date or a name
