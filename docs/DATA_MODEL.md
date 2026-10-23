# Data model

Every table has an `id` and a `tenant_id`, and every query filters by the tenant. Add indexes for every list and search.

```mermaid
erDiagram
  Tenant ||--o{ User : has
  Tenant ||--o{ Customer : owns
  business ||--o{ Customer : has
  User {
    int id PK
    int tenant_id FK
    string email
    string role
  }
  Customer {
    int id PK
    int tenant_id FK
    string name
    string phone_number
    string email
  }
```

## Customer
- `name`: string
- `phone_number`: string
- `email`: string
- belongs to business

