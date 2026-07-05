# Bruno API Testing (OpenCollection YAML)

Reference for creating and running API collections with Bruno CLI using the OpenCollection YAML format.

## Collection Structure

```
<collection-root>/
├── opencollection.yml          # Required — collection manifest
├── .gitignore                  # Must ignore .env.* files
├── .env.staging                # Secrets for staging (gitignored)
├── .env.prod                   # Secrets for prod (gitignored)
├── environments/
│   ├── staging.yml             # One file per environment (committed, no secrets)
│   └── prod.yml
├── health-check.yml            # Requests at root level
├── users/                      # Organize into folders
│   ├── list-users.yml
│   ├── create-user.yml
│   └── delete-user.yml
└── auth/
    └── login.yml
```

## Collection Manifest

`opencollection.yml` — minimal, just names the collection:

```yaml
info:
  name: My API Collection
  type: http
```

## Request File Format

Every request is a `.yml` file with four top-level sections:

```yaml
info:
  name: Create User          # Display name
  type: http                  # Always "http"
  seq: 1                      # Execution order (1, 2, 3...)
  tags:                       # Optional — filter with --tags
    - users
    - write

http:
  method: POST                # GET | POST | PUT | PATCH | DELETE | OPTIONS | HEAD
  url: "{{base_url}}/users"
  params:                     # Query parameters
    - name: page
      value: "1"
      type: query
      disabled: false
  headers:
    - name: Content-Type
      value: application/json
      disabled: false
  auth:                       # See Auth section below
    type: bearer
    token: "{{auth_token}}"
  body:                       # See Body section below
    type: json
    data: |-
      {
        "name": "Test User",
        "email": "test@example.com"
      }

runtime:
  assertions:                 # Declarative checks (no code)
    - expression: res.status
      operator: eq
      value: "200"
  scripts:                    # JavaScript (Chai syntax)
    - type: tests
      code: |-
        test("user created", function() {
          const body = res.getBody();
          expect(body).to.have.property('id');
        });

settings:
  encodeUrl: true
  timeout: 0                  # 0 = no timeout
  followRedirects: true
  maxRedirects: 5
```

## Environment File Format

`environments/<name>.yml`:

```yaml
info:
  name: dev
  type: environment

variables:
  - name: base_url
    value: https://api.example.com
    enabled: true
    secret: false
  - name: auth_token
    value: my-secret-token
    enabled: true
    secret: true              # Masked in output and reports
```

Variables are referenced as `{{variable_name}}` anywhere in request files.

## Secrets Management

Bruno CLI does NOT auto-load `.env` files. Secrets are managed with per-environment dotenv files + `--env-var` at runtime.

### Setup

1. **Environment YMLs** (`environments/*.yml`) are committed with empty values for secrets:
   ```yaml
   - name: user_api_key
     value: ""
     enabled: true
     secret: true
   ```

2. **Per-environment secret files** (`.env.<env-name>`) at the collection root, gitignored:
   ```
   # .env.staging
   user_api_key=my-staging-key

   # .env.prod
   user_api_key=my-prod-key
   ```

3. **`.gitignore`** at the collection root:
   ```
   .env.*
   ```

### Running with secrets

**Before running:** Always glob for `.env.*` files in the collection root first. Source the matching environment file before running — never ask the user for credentials that are already available in dotenv files.

Source the matching `.env.<env>` file before running, then pass secrets via `--env-var`:

```bash
source .env.staging
bru run rate-plans/list-rate-plans.yml --env staging --env-var "user_api_key=$user_api_key"
```

The `source` persists for the shell session — only needed once per terminal. After that:

```bash
bru run bookings/ --env staging --env-var "user_api_key=$user_api_key" -r
```

To switch environments, source the other file:

```bash
source .env.prod
bru run properties/list-properties.yml --env prod --env-var "user_api_key=$user_api_key"
```

### When creating collections

- Always add `.gitignore` with `.env.*` at the collection root
- Create `.env.<env>` files for each environment with placeholder values
- Keep environment YMLs free of real secrets — they get committed

## Auth Types

```yaml
# Bearer token
auth:
  type: bearer
  token: "{{token}}"

# Basic auth
auth:
  type: basic
  username: admin
  password: "{{password}}"

# API key
auth:
  type: apikey
  key: x-api-key
  value: "{{api_key}}"
  placement: header           # header | queryparams

# No auth — omit the auth block entirely (type: none causes errors in bru CLI)

# Inherit from collection
auth: inherit

# Also supported: oauth2, digest, awsv4, ntlm
```

## Body Types

```yaml
# JSON
body:
  type: json
  data: |-
    {"key": "value"}

# Form URL-encoded
body:
  type: form-urlencoded
  data:
    - name: username
      value: spike
      disabled: false

# Plain text
body:
  type: text
  data: "raw text here"

# XML
body:
  type: xml
  data: |-
    <request><id>1</id></request>

# Multipart form (file uploads)
body:
  type: multipart-form
  data:
    - name: file
      value: /path/to/file.pdf
      disabled: false

# GraphQL
body:
  type: graphql
  data: |-
    {
      "query": "{ users { id name } }",
      "variables": {}
    }
```

## Assertion Operators

Used in `runtime.assertions`:

| Operator | Description | Example value |
|----------|-------------|---------------|
| `eq` | Equals | `"200"` |
| `neq` | Not equals | `"404"` |
| `gt` | Greater than | `"0"` |
| `gte` | Greater or equal | `"1"` |
| `lt` | Less than | `"500"` |
| `lte` | Less or equal | `"299"` |
| `contains` | Contains substring | `"success"` |
| `notContains` | Doesn't contain | `"error"` |
| `startsWith` | Starts with | `"https"` |
| `endsWith` | Ends with | `".json"` |
| `matches` | Regex match | `"^[0-9]+$"` |
| `isString` | Type check | *(no value)* |
| `isNumber` | Type check | *(no value)* |
| `isBoolean` | Type check | *(no value)* |
| `isJson` | Valid JSON | *(no value)* |
| `isNull` | Is null | *(no value)* |
| `isDefined` | Not undefined | *(no value)* |
| `isEmpty` | Empty string/array | *(no value)* |

Common expressions:
```yaml
assertions:
  - expression: res.status
    operator: eq
    value: "200"
  - expression: res.body.id
    operator: isDefined
  - expression: res.body.name
    operator: eq
    value: "YourName"
  - expression: res.body.items
    operator: isJson
  - expression: res.headers['content-type']
    operator: contains
    value: "application/json"
```

## Script Types (runtime.scripts)

Three lifecycle hooks:

```yaml
runtime:
  scripts:
    # Runs BEFORE the HTTP request
    - type: before-request
      code: |-
        req.setHeader('X-Timestamp', Date.now().toString());
        req.setHeader('X-Request-Id', uuid());

    # Runs AFTER response, BEFORE tests
    - type: after-response
      code: |-
        const token = res.getBody().access_token;
        bru.setVar('auth_token', token);

    # Test assertions (Chai expect + test() wrapper)
    - type: tests
      code: |-
        test("returns user list", function() {
          const data = res.getBody();
          expect(res.status).to.equal(200);
          expect(data.users).to.be.an('array');
          expect(data.users.length).to.be.greaterThan(0);
        });
```

### Available in scripts

- `res.getBody()` — parsed response body
- `res.status` — HTTP status code
- `res.headers` — response headers
- `req.setHeader(name, value)` — set request header (before-request only)
- `req.getHeader(name)` — get request header
- `bru.setVar(name, value)` — set variable for subsequent requests
- `bru.getVar(name)` — get variable value
- `bru.getEnvVar(name)` — get environment variable
- `expect()` — Chai assertion library
- `test(name, fn)` — test block wrapper

## CLI Reference

### Running

```bash
bru run --env dev                          # Run all requests in collection
bru run request.yml --env dev              # Run single request
bru run users/ --env dev                   # Run folder
bru run users/ --env dev -r                # Run folder recursively
bru run --env dev --tests-only             # Only requests with tests/assertions
bru run --env dev --bail                   # Stop on first failure
bru run --env dev --delay 500              # 500ms between requests
bru run --env dev --tags users,read        # Only tagged requests
bru run --env dev --exclude-tags slow      # Skip tagged requests
```

### Overriding variables

```bash
bru run --env dev --env-var "base_url=https://staging.api.com"
bru run --env dev --env-var "token=$CI_TOKEN"     # From shell env
bru run --env dev --env-var "a=1" --env-var "b=2" # Multiple overrides
```

### Reports

```bash
bru run --env dev -o results.json                  # JSON (default)
bru run --env dev -o results.xml -f junit          # JUnit for CI
bru run --env dev -o results.html -f html          # HTML report
bru run --env dev --reporter-junit j.xml --reporter-html h.html  # Multiple
```

### Other flags

```bash
bru run --env dev --insecure               # Skip TLS verification
bru run --env dev --verbose                # Debug output
bru run --env dev --sandbox developer      # Enable external npm packages
bru run --env dev --csv-file-path data.csv # Data-driven testing
bru run --env dev --parallel               # Parallel CSV iterations
```

## Viewing Response Bodies

`--verbose` does **NOT** display response bodies. To inspect response data:

```bash
bru run request.yml --env staging -o /tmp/output.json
```

Response body is at `results[0].response.data` in the output JSON.

## Conventions

- Collection root identified by `opencollection.yml`
- One request per `.yml` file
- Use `seq` field to control execution order
- Use folders to group related requests (e.g., `users/`, `auth/`)
- Use `disabled: true` on headers/params to toggle without deleting
- Use `secret: true` in environment variables for tokens/passwords
- Use `--sandbox developer` when scripts need external npm packages (default is safe mode)
