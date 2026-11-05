# AI CRM — Available MCP Tools

> **Auto-generated** from the live tool registry by `scripts/generate_available_tools.py`. Do not edit by hand — run the generator to refresh so this catalog can never drift from the code the AI actually sees.

**52 tools** — 34 read-only, 18 write/destructive — across 19 CRM domains.

## Why this MCP is enterprise-grade

Unlike a typical single-tenant CRM MCP that talks straight to a REST API, every call here is **governed and multi-tenant**:

- **Governed execution** — writes route through the *same* unified executor as the in-app AI, so RBAC, policy checks, audit logging, and idempotency are enforced identically whether a change comes from the app or an MCP client.
- **Workspace + user scoped** — every request is authenticated and scoped to a workspace and user; tools never leak cross-tenant data.
- **Resilient by default** — shared HTTP client with retries, circuit breaker, rate limiting, response caching, and backpressure.
- **Idempotent writes** — create/update/delete accept an idempotency key and de-duplicate retries, so a flaky connection never double-creates records.
- **Safe by design** — no arbitrary code execution. Every tool is schema-validated with an explicit input contract (a deliberate security choice for a multi-tenant server).

## Tool selection guide

| If the user wants to… | Use | Kind |
| --- | --- | --- |
| Answer a question / see / count / filter records | `list_*`, `get_*`, `*_search` | 🟢 read-only |
| Add a record | `create_*`, `add_*` | 🟠 write |
| Change a record | `update_*` | 🟠 write |
| Delete a record (confirm first) | `delete_*` | 🔴 destructive |

Read tools are cached and safe to call freely. Write tools are governed and idempotent — call them once you have what you need. **Destructive** tools require explicit user confirmation.

## Tools by domain

### Identity & Session

- [`get_me`](#get_me) — 🟢 read-only
- [`whoami`](#whoami) — 🟢 read-only

#### `get_me`

🟢 read-only  ·  v1.0.0

Alias of `whoami`. Returns the current user's profile and the active workspace id — use to resolve 'me'/'my' before first-person queries. Read-only.

_No parameters._


#### `whoami`

🟢 read-only  ·  v1.0.0

Use to identify the current user and active workspace before answering first-person requests like 'my tasks', 'deals assigned to me', or 'projects I'm part of'. Returns the caller's profile (id, name, email) and workspace id. Read-only.

_No parameters._


### Contacts & Leads

- [`contacts_search`](#contacts_search) — 🟢 read-only
- [`get_contact`](#get_contact) — 🟢 read-only
- [`search_contacts`](#search_contacts) — 🟢 read-only
- [`add_contact_note`](#add_contact_note) — 🟠 write
- [`create_contact`](#create_contact) — 🟠 write
- [`delete_contact`](#delete_contact) — 🔴 destructive
- [`update_contact`](#update_contact) — 🟠 write

#### `contacts_search`

🟢 read-only  ·  governed (RBAC + audit)  ·  v1.0.0

Use when the user wants to find, list, count, or filter contacts/leads with combined filters (status, source, saved filter). Read-only. Same as search_contacts.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | no | default=None |
| `search` | string | no | default=None |
| `limit` | integer | no | minimum=1, maximum=200, default=20 |
| `page` | integer | no | default=None |
| `cursor` | string | no | default=None |
| `status` | string | no | default=None |
| `source` | string | no | default=None |
| `filter_id` | string | no | default=None |
| `criteria` | object | no | default=None |
| `filters` | object | no | default=None |
| `unclaimed_leads` | boolean | no | default=None |
| `unclaimed_pond_id` | string | no | default=None |
| `sort_by` | string | no | default=None |
| `sort_order` | string | no | default=None |


#### `get_contact`

🟢 read-only  ·  governed (RBAC + audit)  ·  v1.0.0

Use when the user asks for the full details of ONE specific contact you already have the id for. Read-only. To search by name, use search_contacts first.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |


#### `search_contacts`

🟢 read-only  ·  governed (RBAC + audit)  ·  v1.0.0

Use when the user wants to find, list, count, or filter contacts or leads (e.g. 'find John', 'how many leads from Facebook'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | no | default=None |
| `search` | string | no | default=None |
| `limit` | integer | no | minimum=1, maximum=200, default=20 |
| `page` | integer | no | default=None |
| `cursor` | string | no | default=None |
| `status` | string | no | default=None |
| `source` | string | no | default=None |
| `filter_id` | string | no | default=None |
| `criteria` | object | no | default=None |
| `filters` | object | no | default=None |
| `unclaimed_leads` | boolean | no | default=None |
| `unclaimed_pond_id` | string | no | default=None |
| `sort_by` | string | no | default=None |
| `sort_order` | string | no | default=None |


#### `add_contact_note`

🟠 write  ·  v1.0.0

Use when the user wants to log a note or comment on a contact's record (e.g. 'add a note to John that he prefers email').

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |
| `content` | string | yes | minLength=1, maxLength=10000 |
| `title` | string | no | default=None |


#### `create_contact`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to add a new contact or lead (e.g. 'add a contact named…').

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | minLength=1, maxLength=200 |
| `email` | string | no | default=None |
| `phone` | string | no | default=None |
| `status` | string | no | default=None |


#### `delete_contact`

🔴 destructive  ·  v1.0.0

Use ONLY when the user explicitly asks to delete or remove a contact. Destructive and irreversible — confirm intent first.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |


#### `update_contact`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to change a contact's fields — name, email, phone, status, or company (e.g. 'update John's phone number').

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |
| `first_name` | string | no | default=None |
| `last_name` | string | no | default=None |
| `email` | string | no | default=None |
| `phone` | string | no | default=None |
| `status` | string | no | default=None |
| `company` | string | no | default=None |


### Deals & Pipelines

- [`list_deals`](#list_deals) — 🟢 read-only
- [`list_pipelines`](#list_pipelines) — 🟢 read-only
- [`create_deal`](#create_deal) — 🟠 write
- [`create_pipeline`](#create_pipeline) — 🟠 write
- [`delete_deal`](#delete_deal) — 🔴 destructive
- [`update_deal`](#update_deal) — 🟠 write
- [`update_deal_stage`](#update_deal_stage) — 🟠 write
- [`update_pipeline`](#update_pipeline) — 🟠 write

#### `list_deals`

🟢 read-only  ·  v1.0.0

Use when the user wants to list, count, or filter deals/opportunities (sales pipeline). Not for Projects — use projects tools for those. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `stage` | string | no | default=None |
| `status` | string | no | default=None |
| `assigned_to` | string | no | default=None |
| `search` | string | no | default=None |
| `page` | integer | no | minimum=1, maximum=10000, default=1 |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |
| `sort_by` | string | no | maxLength=64, default=created_at |
| `sort_order` | string | no | pattern=^(?i)(asc|desc)$, default=desc |


#### `list_pipelines`

🟢 read-only  ·  v1.0.0

Use when the user wants to see the sales pipeline — stages and the deals within each (e.g. 'show me the pipeline', 'what's in each stage'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `assigned_to` | string | no | default=None |


#### `create_deal`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to add a new deal or opportunity to the sales pipeline.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | minLength=1, maxLength=255 |
| `description` | string | no | default=None |
| `value` | number | no | minimum=0, default=0 |
| `currency` | string | no | maxLength=8, default=USD |
| `stage` | string | no | default=None |
| `probability` | integer | no | minimum=0, maximum=100, default=0 |
| `primary_contact_id` | string | no | default=None |


#### `create_pipeline`

🟠 write  ·  v1.0.0

Use when the user wants to add a new pipeline/opportunity stage to the sales process.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | minLength=1, maxLength=255 |
| `description` | string | no | maxLength=2000, default= |
| `probability` | integer | no | minimum=0, maximum=100, default=0 |
| `stage_order` | integer | no | default=0 |
| `is_closed` | boolean | no | default=False |
| `is_won` | boolean | no | default=False |
| `color` | string | no | default=None |


#### `delete_deal`

🔴 destructive  ·  v1.0.0

Use ONLY when the user explicitly asks to delete or remove a deal/opportunity. Destructive and irreversible — confirm intent first.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `deal_id` | string | yes |  |


#### `update_deal`

🟠 write  ·  v1.0.0

Use when the user wants to change a deal's fields — value, name, status, close date, etc. To only move stages, prefer update_deal_stage.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `deal_id` | string | yes |  |
| `name` | string | no | default=None |
| `description` | string | no | default=None |
| `value` | number | no | default=None |
| `currency` | string | no | default=None |
| `stage` | string | no | default=None |
| `probability` | integer | no | default=None |
| `status` | string | no | default=None |
| `primary_contact_id` | string | no | default=None |


#### `update_deal_stage`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to move/advance a deal to a different pipeline stage (e.g. 'move this deal to Negotiation', 'mark it won').

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `deal_id` | string | yes |  |
| `stage` | string | yes | minLength=1, maxLength=100 |


#### `update_pipeline`

🟠 write  ·  v1.0.0

Use when the user wants to rename or reconfigure an existing pipeline/opportunity stage.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `pipeline_id` | string | yes |  |
| `name` | string | no | default=None |
| `description` | string | no | default=None |
| `probability` | integer | no | default=None |
| `stage_order` | integer | no | default=None |
| `is_closed` | boolean | no | default=None |
| `is_won` | boolean | no | default=None |
| `color` | string | no | default=None |


### Tasks

- [`list_tasks`](#list_tasks) — 🟢 read-only
- [`create_task`](#create_task) — 🟠 write
- [`update_task_status`](#update_task_status) — 🟠 write

#### `list_tasks`

🟢 read-only  ·  governed (RBAC + audit)  ·  v1.0.0

Use when the user wants to see, count, filter, or find tasks, to-dos, or follow-ups (e.g. 'my open tasks', 'how many tasks are pending'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |
| `cursor` | string | no | default=None |
| `board_id` | string | no | default=None |
| `search` | string | no | default=None |


#### `create_task`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to add a new task, to-do, follow-up, or reminder (e.g. 'create a task to…', 'remind me to…'). Creates it in the workspace.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `title` | string | yes | minLength=1, maxLength=1000 |
| `contact_id` | string | no | default=None |
| `description` | string | no | default=None |
| `board_id` | string | no | default=None |
| `group_id` | string | no | default=None |
| `priority` | string | no | default=None |
| `status` | string | no | default=None |
| `idempotency_key` | string | no | default=None |


#### `update_task_status`

🟠 write  ·  governed (RBAC + audit + idempotent)  ·  v1.0.0

Use when the user wants to mark a task done/complete/in-progress or otherwise change a task's status (e.g. 'mark task X as done', 'move it to in progress').

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `task_id` | string | yes |  |
| `status` | string | yes | minLength=1, maxLength=64 |
| `idempotency_key` | string | no | default=None |


### Task Boards

- [`list_boards`](#list_boards) — 🟢 read-only
- [`create_board`](#create_board) — 🟠 write
- [`delete_board`](#delete_board) — 🔴 destructive
- [`update_board`](#update_board) — 🟠 write

#### `list_boards`

🟢 read-only  ·  v1.0.0

Use when the user wants to see the task boards (kanban) in the workspace, or to find a board id before creating/moving a task. Read-only.

_No parameters._


#### `create_board`

🟠 write  ·  v1.0.0

Use when the user wants to add a new task board (kanban) to organize tasks.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | minLength=1, maxLength=255 |
| `description` | string | no | default=None |
| `is_private` | boolean | no | default=True |


#### `delete_board`

🔴 destructive  ·  v1.0.0

Use ONLY when the user explicitly asks to delete a task board. Destructive — this removes the board and confirm intent first.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `board_id` | string | yes |  |


#### `update_board`

🟠 write  ·  v1.0.0

Use when the user wants to rename or reconfigure an existing task board.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `board_id` | string | yes |  |
| `name` | string | no | default=None |
| `description` | string | no | default=None |
| `is_default` | boolean | no | default=None |
| `is_private` | boolean | no | default=None |


### Activities

- [`list_activities`](#list_activities) — 🟢 read-only

#### `list_activities`

🟢 read-only  ·  v1.0.0

Use when the user wants the activity history/timeline for a specific contact (calls, messages, status changes) — you must have the contact_id. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |
| `event_type` | string | no | Optional filter, e.g. CALL, WHATSAPP, EMAIL, STATUS_CHANGED. |


### Ai_Employees

- [`get_ai_employee_mission`](#get_ai_employee_mission) — 🟢 read-only
- [`list_ai_employee_missions`](#list_ai_employee_missions) — 🟢 read-only
- [`list_ai_employees`](#list_ai_employees) — 🟢 read-only

#### `get_ai_employee_mission`

🟢 read-only  ·  v1.0.0

Get one durable AI employee mission and its action trail. Read-only. Workspace isolation is enforced by the FastAPI endpoint.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `mission_id` | string | yes | minLength=8, maxLength=80 |


#### `list_ai_employee_missions`

🟢 read-only  ·  v1.0.0

List durable AI employee missions for the current workspace. Read-only. Optional status filter: queued|running|waiting|needs_approval|completed|failed.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `status` | string | no | default=None |
| `limit` | integer | no | minimum=1, maximum=200, default=50 |


#### `list_ai_employees`

🟢 read-only  ·  v1.0.0

List AI employees in the current workspace (name, role, autonomy, manager). Read-only. Workspace is taken from auth context.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `search` | string | no | default=None |
| `is_active` | boolean | no | default=None |
| `limit` | integer | no | minimum=1, maximum=200, default=50 |


### Calendar

- [`list_appointments`](#list_appointments) — 🟢 read-only

#### `list_appointments`

🟢 read-only  ·  v1.0.0

Use when the user wants to see calendar events/appointments/meetings in a date window (e.g. 'my meetings today', 'appointments this week'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `date_range` | string | no | Natural language range: 'today', 'this week', 'next 7 days', etc. Defaults to the next 30 days if omitted. |
| `date_from` | string | no | Explicit start date YYYY-MM-DD. |
| `date_to` | string | no | Explicit end date YYYY-MM-DD. |
| `only_mine` | boolean | no | default=False |


### Calls

- [`list_calls`](#list_calls) — 🟢 read-only

#### `list_calls`

🟢 read-only  ·  v1.0.0

Use when the user wants to see phone call logs/recordings, optionally by direction or date range (e.g. 'calls this week', 'outbound calls today'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `limit` | integer | no | minimum=1, maximum=300, default=50 |
| `offset` | integer | no | minimum=0, default=0 |
| `direction` | string | no | default=None |
| `date_range` | string | no | Natural language range: 'today', 'last 7 days', 'this month', etc. |
| `date_from` | string | no | Explicit start date YYYY-MM-DD. |
| `date_to` | string | no | Explicit end date YYYY-MM-DD. |


### Custom_Reports

- [`describe_report_dataset`](#describe_report_dataset) — 🟢 read-only
- [`list_report_components`](#list_report_components) — 🟢 read-only
- [`list_report_datasets`](#list_report_datasets) — 🟢 read-only
- [`preview_report`](#preview_report) — 🟢 read-only
- [`publish_report`](#publish_report) — 🟢 read-only
- [`validate_report`](#validate_report) — 🟢 read-only
- [`create_report`](#create_report) — 🟠 write
- [`move_report_component`](#move_report_component) — 🟠 write
- [`update_report`](#update_report) — 🟠 write

#### `describe_report_dataset`

🟢 read-only  ·  v1.0.0

Describe one Universal Report Builder dataset including metrics, dimensions, and allowed filters. Read-only. Do not invent metrics that are not listed.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `dataset_id` | string | yes | minLength=1, maxLength=64 |


#### `list_report_components`

🟢 read-only  ·  v1.0.0

List Universal Report Builder component types (kpi, charts, table, text). Use these types only when composing a definition. Read-only.

_No parameters._


#### `list_report_datasets`

🟢 read-only  ·  v1.0.0

List Universal Report Builder datasets (projects, tasks, contacts, and other registered sources). Use before creating a custom report. Read-only.

_No parameters._


#### `preview_report`

🟢 read-only  ·  v1.0.0

Preview a custom report definition or existing report_id without publishing. Returns per-component data. Read-only against live CRM sources.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `definition` | object | no | default=None |
| `report_id` | string | no | default=None |
| `context` | object | no | default=None |


#### `publish_report`

🟢 read-only  ·  v1.0.0

Publish the current draft of a custom report. Customer assignments stay pinned to the previous published version until reassigned.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `report_id` | string | yes |  |
| `version_id` | string | no | default=None |


#### `validate_report`

🟢 read-only  ·  v1.0.0

Validate a Universal Report Builder DSL definition (or the latest draft for report_id). Rejects SQL/code keys and unknown datasets. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `definition` | object | no | default=None |
| `report_id` | string | no | default=None |


#### `create_report`

🟠 write  ·  v1.0.0

Create a Universal Report Builder draft from a report DSL JSON. No SQL, no JavaScript, no React. Use list_report_datasets and list_report_components first.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | minLength=1, maxLength=200 |
| `description` | string | no | default=None |
| `scope` | string | no | maxLength=32, default=workspace |
| `definition` | object | no | default=None |


#### `move_report_component`

🟠 write  ·  v1.0.0

Move or resize one component on a custom report draft (12-column grid). Loads the current draft, updates layout, and saves. No SQL.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `report_id` | string | yes |  |
| `component_id` | string | yes | minLength=1, maxLength=64 |
| `x` | integer | no | default=None |
| `y` | integer | no | default=None |
| `w` | integer | no | default=None |
| `h` | integer | no | default=None |


#### `update_report`

🟠 write  ·  v1.0.0

Update a custom report draft. Pass a full DSL definition to replace the canvas, and/or name/description/scope. No SQL or executable code.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `report_id` | string | yes |  |
| `name` | string | no | default=None |
| `description` | string | no | default=None |
| `scope` | string | no | default=None |
| `definition` | object | no | default=None |


### Discovery

- [`find_custom_field`](#find_custom_field) — 🟢 read-only
- [`list_deal_stages`](#list_deal_stages) — 🟢 read-only
- [`list_lead_sources`](#list_lead_sources) — 🟢 read-only

#### `find_custom_field`

🟢 read-only  ·  v1.0.0

Use before setting a custom field to resolve the user's wording (e.g. 'budget', 'industry') to a real custom-field definition (id, type, options) for contacts/deals/tasks. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `keyword` | string | yes | minLength=1, maxLength=128 |
| `entity_type` | string | no | pattern=^(contact|deal|task|workforce_member)$, default=contact |


#### `list_deal_stages`

🟢 read-only  ·  v1.0.0

Use to see the deal/opportunity pipeline stages, or to resolve a stage name before creating/moving a deal. Read-only.

_No parameters._


#### `list_lead_sources`

🟢 read-only  ·  v1.0.0

Use to see the configured lead/contact sources, or to resolve a source name before filtering/creating a contact. Read-only.

_No parameters._


### Documents

- [`list_documents`](#list_documents) — 🟢 read-only
- [`search_documents`](#search_documents) — 🟢 read-only

#### `list_documents`

🟢 read-only  ·  v1.0.0

List CRM documents in the current workspace. Read-only. Workspace is taken from auth context.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | no | default=None |
| `status` | string | no | default=None |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |
| `page` | integer | no | minimum=1, default=1 |


#### `search_documents`

🟢 read-only  ·  v1.0.0

Search CRM documents by keyword in the current workspace. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | yes | minLength=1, maxLength=512 |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |


### Duplicates

- [`check_duplicates`](#check_duplicates) — 🟢 read-only

#### `check_duplicates`

🟢 read-only  ·  v1.0.0

Use BEFORE creating a contact to check whether one already exists with the same email, phone, or name. Returns any likely matches so you can update instead of duplicating. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `email` | string | no | default=None |
| `phone` | string | no | default=None |
| `name` | string | no | default=None |


### Inbox

- [`list_inbox_conversations`](#list_inbox_conversations) — 🟢 read-only

#### `list_inbox_conversations`

🟢 read-only  ·  v1.0.0

List inbox conversations for the current workspace (email, WhatsApp, SMS, calls). Read-only. Workspace is taken from auth context.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `channel` | string | no | email|whatsapp|call|sms |
| `inbox_status` | string | no | inbox|assigned|draft|sent|closed |
| `unread_only` | boolean | no | default=False |
| `limit` | integer | no | minimum=1, maximum=50, default=20 |


### Notes

- [`list_contact_notes`](#list_contact_notes) — 🟢 read-only
- [`search_notes`](#search_notes) — 🟢 read-only

#### `list_contact_notes`

🟢 read-only  ·  v1.0.0

Use when the user wants to read the notes logged on a specific contact (you must have the contact_id). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `contact_id` | string | yes |  |


#### `search_notes`

🟢 read-only  ·  v1.0.0

Use when the user wants to find notes across all contacts by keyword (e.g. 'find notes mentioning refund'). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | yes | minLength=2, maxLength=512 |
| `limit` | integer | no | minimum=1, maximum=100, default=20 |


### Phones

- [`list_workspace_phone_numbers`](#list_workspace_phone_numbers) — 🟢 read-only

#### `list_workspace_phone_numbers`

🟢 read-only  ·  v1.0.0

List workspace phone numbers and their status. Read-only metadata. Does not place calls. Workspace is taken from auth context.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `list_scope` | string | no | outbound = caller-ID picker; management = admin list |


### Projects

- [`list_projects`](#list_projects) — 🟢 read-only

#### `list_projects`

🟢 read-only  ·  v1.0.0

Use when the user wants to list, count, or filter PROJECTS from the Projects module (e.g. 'my projects', 'how many active projects'). Permission-scoped to the user. This is NOT deals/opportunities — use list_deals for those. Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `limit` | integer | no | minimum=1, maximum=100, default=50 |
| `page` | integer | no | minimum=1, default=1 |
| `status` | string | no | default=None |
| `search` | string | no | default=None |


### Reporting

- [`generate_report`](#generate_report) — 🟢 read-only

#### `generate_report`

🟢 read-only  ·  v1.0.0

Use when the user asks for an aggregate/summary/report/analytics number rather than a list of records — e.g. 'contacts by source', 'pipeline value', 'task summary', 'calls by rep this month'. Pick a report from the catalog; no custom queries. Read-only. Available reports: activity_summary, appointments_summary, calls_by_rep, contact_creation_trend, contacts_by_source, contacts_statistics, contacts_total, deals_aggregate, deals_by_lead_source, lead_distribution, member_closed_deals_leaderboard, pipeline_value, tasks_summary, workspace_activity_digest.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `report` | string | yes | One of the whitelisted report names. |
| `date_range` | string | no | Natural language window ('this month', 'last 30 days') for date-aware reports. Ignored by point-in-time reports. |
| `start_date` | string | no | Explicit start date YYYY-MM-DD. |
| `end_date` | string | no | Explicit end date YYYY-MM-DD. |


### Users

- [`list_users`](#list_users) — 🟢 read-only

#### `list_users`

🟢 read-only  ·  v1.0.0

Use when the user wants to see the people/team members in the workspace, or to find a member's id before assigning work or @-mentioning them. Returns human members (id, name, email, role). Read-only.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `page` | integer | no | minimum=1, default=1 |
| `limit` | integer | no | minimum=1, maximum=100, default=50 |


---

_Regenerate with_ `./.venv/bin/python scripts/generate_available_tools.py`.
