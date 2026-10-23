# Requirements

Version 1: **The must-haves only**. The source of truth is `blueprint.json`; this file explains it.

## Roles
| Role | What they do |
|---|---|
| OWNER | RUNS THE BUSINESS AND PAY |

## Features
| Id | Feature | Priority | Used by | AI | What it does |
|---|---|---|---|---|---|
| F1 | AI MESSAGE PARSER | Must, version 1 | OWNER | yes | Converts raw text order message into structured data (product name , quantity,date,addres ,recipe) |
| F2 | Order Management Dashboard | Must, version 1 | OWNER |  | Display clean overview of all active orders, payment statuses and delivery dates in one places |
| F3 | Recipe & Ingredient Costing | Must, version 1 | OWNER | yes | Records raw material lists and ingredient costs per recipe to calculate unit production costs. |
| F4 | Production Planning | Must, version 1 | OWNER |  | Aggregates all orders for a specific date to calculate the total batch quantities required for cooking/baking. |
| F5 | Automatic Grocery List | Must, version 1 | OWNER |  | Automatically generates a raw material shopping list based on daily or weekly production plans |
| F6 | Profit & Loss Calculator | Must, version 1 | OWNER |  | Calculates estimated net profit per order after deducting raw material costs. |
| F7 | Customer Database | Should | OWNER |  | Stores basic customer profiles (name, phone number, order history, and address) for repeat orders. |
| F8 | Payment Status Tracker | Should | OWNER |  | Tracks customer payment statuses (deposit paid, unpaid, or fully paid) to prevent revenue leakage. |
| F9 | MESSAGE BOX | Must, version 1 | OWNER |  | WHERE CUSTOMER CAN CHHAT OWNER STATING THEIR ORDERS |

## Use cases (version 1)

### UC1 · AI MESSAGE PARSER (F1)
- Actor: OWNER
- Goal: Converts raw text order message into structured data (product name , quantity,date,addres ,recipe)

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f1_ai_message_parser.py`):
- (not written: the test file holds one failing reminder)

### UC2 · Order Management Dashboard (F2)
- Actor: OWNER
- Goal: Display clean overview of all active orders, payment statuses and delivery dates in one places

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f2_order_management_dashboard.py`):
- (not written: the test file holds one failing reminder)

### UC3 · Recipe & Ingredient Costing (F3)
- Actor: OWNER
- Goal: Records raw material lists and ingredient costs per recipe to calculate unit production costs.

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f3_recipe_ingredient_costing.py`):
- (not written: the test file holds one failing reminder)

### UC4 · Production Planning (F4)
- Actor: OWNER
- Goal: Aggregates all orders for a specific date to calculate the total batch quantities required for cooking/baking.

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f4_production_planning.py`):
- (not written: the test file holds one failing reminder)

### UC5 · Automatic Grocery List (F5)
- Actor: OWNER
- Goal: Automatically generates a raw material shopping list based on daily or weekly production plans

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f5_automatic_grocery_list.py`):
- (not written: the test file holds one failing reminder)

### UC6 · Profit & Loss Calculator (F6)
- Actor: OWNER
- Goal: Calculates estimated net profit per order after deducting raw material costs.

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f6_profit_loss_calculator.py`):
- (not written: the test file holds one failing reminder)

### UC7 · MESSAGE BOX (F9)
- Actor: OWNER
- Goal: WHERE CUSTOMER CAN CHHAT OWNER STATING THEIR ORDERS 

Main steps:
(not written)

Errors and edge cases:
- (not written)

Acceptance criteria (tests in `tests/acceptance/test_f9_message_box.py`):
- (not written: the test file holds one failing reminder)

## Integrations
- Google Sheets or Excel
- Calendar
- Online payment

## Platforms
- A web app (works on phones too)

## Out of scope for version 1
- Anything not listed above.

## Data
See docs/DATA_MODEL.md.
