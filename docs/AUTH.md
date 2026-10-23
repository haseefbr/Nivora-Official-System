# Authentication and authorization

## Authentication: who you are
- Email magic link
- Google sign-in
- Phone number with a one-time code
- Email and password, from a proven library (never hand-built)

Options:
- Verify the email address
- Slow down and lock out after failed sign-ins
- Two-factor sign-in for owners and admins
- Password reset by email
- Use a proven library or auth service; never store a password yourself.
- Sessions are secure, HTTP-only cookies; sign-out ends the session on the server.

## Authorization: what you may do
- Deny by default: a route with no rule below is refused.
- Check the permission on the server, on every request; pages only hide what the server already refuses.
- Tenants: One database, tenant id on every row and key. Every row and key carries the tenant id, and every query filters by it. This is always on.

| Permission | OWNER |
|---|---|
| AI MESSAGE PARSER | yes |
| Order Management Dashboard | yes |
| Recipe & Ingredient Costing | yes |
| Production Planning | yes |
| Automatic Grocery List | yes |
| Profit & Loss Calculator | yes |
| Customer Database | yes |
| Payment Status Tracker | yes |
| MESSAGE BOX | yes |
| Shop assistant | yes |
| Manage team and roles | yes |
| Billing and plan | yes |
| Business settings | yes |
| AI settings | yes |
| Usage and logs | yes |
| Export data | yes |

Options:
- None
