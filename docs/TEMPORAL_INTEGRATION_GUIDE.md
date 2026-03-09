# Temporal.io Integration Guide for Invoice Automation

This guide explains **what Temporal.io is**, **why it fits your workflow**, and **how to incorporate it** into this project so you can track status and proceed to the next action based on that status.

---

## 1. What is Temporal.io?

**Temporal** is a durable workflow orchestration platform. Instead of one long-running HTTP request doing everything (Document Intelligence → iGentic → DB → SharePoint), you define:

- **Workflows** – The “recipe”: which steps run, in what order, and **what to do next based on status**.
- **Activities** – The actual side effects (call Document Intelligence, call iGentic, insert into DB, upload to SharePoint). Each activity can be retried independently.

Temporal stores **full execution history** for every workflow run. So you get:

- **Status tracking** – You can query “what step is this invoice/SOW in?” and “what’s the status of each step?”
- **Next action based on status** – The workflow code can branch: e.g. if iGentic returns `status: error`, retry or send to manual review; if `status: success`, continue to DB and SharePoint.
- **Resilience** – If a step fails, Temporal can retry it without re-running the whole pipeline. If the process crashes, the workflow resumes from the last recorded step.
- **Visibility** – UIs (Temporal Web UI or your own) can show progress and history per invoice/SOW.

---

## 2. How This Maps to Your Current Flows

### Current: SOW Upload (single HTTP request)

Today in `sow_upload/__init__.py` the flow is linear in one request:

1. Parse multipart → validate file  
2. **Document Intelligence** (`analyze_invoice_bytes`)  
3. **iGentic SOW** (`process_sow_with_igentic`) – if `status == "error"` you return 502 and stop  
4. Extract SOW fields  
5. **SharePoint upload** (optional)  
6. **DB insert** (`insert_sow`)

There is no durable “status” stored for each step; if the request times out or fails after step 3, you have no built-in way to resume.

### Current: Invoice Upload (single HTTP request)

Similarly in `upload/__init__.py`:

1. Parse multipart → validate → optional JWT  
2. **Document Intelligence**  
3. **iGentic** (invoice orchestrator)  
4. Extract fields → duplicate check → vendor org check  
5. **SharePoint upload**  
6. **SQL** insert/update  
7. **Excel** update  

Again, all in one request; status is only “success” or “error” at the end.

### With Temporal: Same Steps as Activities, Flow as Workflow

| Current step              | Becomes in Temporal     | Status you can track        |
|---------------------------|-------------------------|-----------------------------|
| Document Intelligence     | Activity                 | `di_pending` → `di_done` / `di_failed` |
| iGentic (SOW or Invoice)  | Activity                 | `igentic_pending` → `igentic_success` / `igentic_error` |
| Extract fields            | Part of workflow logic   | -                           |
| SharePoint upload         | Activity                 | `sharepoint_pending` → `sharepoint_done` / `sharepoint_failed` |
| DB insert/update          | Activity                 | `db_pending` → `db_done` / `db_failed` |
| Excel update (invoice)    | Activity                 | `excel_pending` → `excel_done` / `excel_failed` |

The **workflow** code then:

- Runs activities in sequence (or parallel where it makes sense).
- **Branches on status**: e.g. if iGentic returns error, don’t call SharePoint or DB; instead “send to manual review” or retry.
- Exposes **status** (and optionally a “next recommended action”) via Temporal **queries** or by writing status to your DB/API.

So: **Temporal gives you a single place to define “what happens next” based on the status of each step.**

---

## 3. How to Incorporate Temporal in This Project

### Option A: Azure Function starts workflow; worker runs elsewhere (recommended to start)

1. **Temporal Server** – Run Temporal Server (e.g. Docker, or [Temporal Cloud](https://temporal.io/cloud)) and get a connection endpoint (and optional namespace).
2. **Worker process** – A long-running Python process (not an HTTP-triggered function) that:
   - Connects to Temporal.
   - Registers your **workflows** and **activities** (your existing helpers become activities: `analyze_invoice_bytes`, `process_sow_with_igentic`, `insert_sow`, etc.).
   - Polls for work and executes it.
   - Can run on: a VM, Azure Container Instances, or a dedicated “worker” Azure Function (e.g. queue-triggered or timer + long-running task).
3. **Azure Function (HTTP)** – Your existing `sow_upload` / `upload` endpoints:
   - Parse and validate the request (file, auth) as today.
   - Instead of doing Document Intelligence → iGentic → DB in-process, they **start a Temporal workflow** (e.g. `SowProcessingWorkflow` or `InvoiceProcessingWorkflow`) with the needed inputs (e.g. file bytes or a reference, filename, sow_id / invoice_id).
   - Return immediately with `workflow_id` (and optionally `run_id`) so the client can poll for status.
4. **Status and next action**:
   - Your app can **query** the workflow (Temporal’s “query” feature) to get current status and “next action.”
   - Optionally, at the end of each activity (or in the workflow after an activity), **update your DB** with a status column (e.g. `workflow_status`, `last_step`, `next_action`) so your existing dashboards/APIs can show status without calling Temporal.

This way you **keep your existing Azure Functions for HTTP and validation**, and move the “heavy” pipeline into Temporal so status and next-action logic live in one place.

### Option B: Full worker in Azure

- Run the Temporal **worker** as an Azure App Service (long-running) or in AKS/Container Apps.
- HTTP-triggered Functions only start workflows and possibly query them; all execution runs in the worker.

### Option C: Hybrid status in DB only (minimal Temporal)

- Use Temporal only for **orchestration and retries**; at each step the workflow writes status to your PostgreSQL (e.g. `invoices.workflow_status`, `sow_documents.workflow_status`).
- Your “next action” logic can then be implemented either:
  - Inside the Temporal workflow (recommended), or  
  - In your app by reading status from the DB and calling different APIs.

---

## 4. Costs

### Self-hosted Temporal (open source)

- **Temporal itself**: free (Apache 2.0). You pay only for the infrastructure you run it on:
  - Servers/containers for Temporal Server (and optional UI)
  - Database (PostgreSQL or MySQL) for Temporal’s state and history
- **Worker**: runs on your own VM/container (e.g. Azure VM, Container Apps, AKS) — normal Azure compute/storage costs apply.

Good option if you have capacity to operate and maintain the stack and want to control cost at scale.

### Temporal Cloud (managed)

Temporal offers a managed service with tiered plans (pricing as of 2025; confirm on [temporal.io/pricing](https://temporal.io/pricing)):

| Plan | Starting price | Included |
|------|-----------------|----------|
| **Essentials** | ~$100/month | 1M Actions, 1GB active storage, 40GB retained storage |
| **Business** | ~$500/month | 2.5M Actions, more storage, faster support |
| **Enterprise / Mission Critical** | Contact sales | Higher limits, SSO, 24/7 support |

- **Actions** (main billable unit): workflow start, each activity run (and each retry), timers, signals, queries, etc. For one SOW or invoice run (e.g. 1 start + 4–5 activities), you’re in the ballpark of **~5–15 actions** per document; 1M actions can be on the order of tens of thousands to hundreds of thousands of processed documents per month, depending on retries and workflow design.
- **Overage**: beyond plan limits, pay-as-you-go (e.g. per million actions, per GB-hour for storage).
- **Free credits**: new customers often get **$1,000 in credits**; startups (under ~$30M funding) may qualify for **$6,000** via Temporal’s startup program.

### Your project (rough ballpark)

- **Low volume** (e.g. hundreds of invoices/SOWs per month): self-hosted can be very cheap (a small VM + DB); Temporal Cloud Essentials or free credits may cover you for a long time.
- **Higher volume**: compare self-hosted (infra + ops) vs Temporal Cloud plan + overage; Cloud avoids running and upgrading Temporal Server yourself.

### Other costs (unchanged by Temporal)

- **Azure**: Document Intelligence, Azure Functions, SharePoint, SQL DB, etc. stay as today; adding a **worker** (VM/container) adds only that compute cost if you run the worker in Azure.
- **iGentic / other APIs**: same as today; Temporal does not add API fees.

---

## 5. High-Level Architecture

```
[Client] --> POST /api/sow_upload (or /api/upload)
                |
                v
         [Azure Function]
         - Validate request & file
         - Start Temporal workflow (SowWorkflow / InvoiceWorkflow)
         - Return workflow_id (+ run_id)
                |
                v
         [Temporal Server]
         - Stores workflow state and history
                |
                v
         [Temporal Worker]
         - Runs workflow code
         - Executes activities (DI, iGentic, SharePoint, DB, Excel)
         - Decides next step based on status (e.g. on iGentic error -> notify / manual review)
                |
                v
         [Your DB / APIs]
         - Optionally store workflow_status, last_step, next_action for UI
```

**Status and next action:**  
- Either **query the workflow** via Temporal client (get current step, result of last activity, custom “status” and “next_action” you set in workflow state),  
- Or **read from DB** after the worker updates status at each step.

---

## 6. Example: SOW Workflow with Status-Driven Next Action

Conceptually, your SOW workflow could look like this (pseudocode; real code would use the Temporal Python SDK):

```python
# workflow.py (runs in Temporal worker)
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn
class SowProcessingWorkflow:
    @workflow.run
    async def run(self, input: SowInput) -> SowResult:
        # 1) Document Intelligence
        workflow.logger.info("SOW workflow started", extra={"sow_id": input.sow_id})
        di_result = await workflow.execute_activity(
            run_document_intelligence,
            input.file_content_base64,
            input.filename,
            start_to_close_timeout=timedelta(minutes=2),
        )
        if not di_result or di_result.get("status") == "no_di":
            return SowResult(status="failed", step="document_intelligence", next_action="retry_or_manual")

        # 2) iGentic SOW
        igentic_result = await workflow.execute_activity(
            run_process_sow_igentic,
            args=[di_result, input.sow_id],
            start_to_close_timeout=timedelta(minutes=3),
        )
        if igentic_result.get("status") == "error":
            # Next action based on status: do not proceed to DB/SharePoint
            return SowResult(
                status="failed",
                step="igentic",
                next_action="manual_review",
                detail=igentic_result.get("error"),
            )

        sow_fields = extract_sow_fields(igentic_result)

        # 3) SharePoint (optional)
        pdf_url = None
        try:
            pdf_url = await workflow.execute_activity(
                run_upload_sharepoint,
                args=[input.file_content_base64, input.filename, "Invoices/SOWs"],
                start_to_close_timeout=timedelta(minutes=1),
            )
        except Exception as e:
            workflow.logger.warning("SharePoint upload failed, continuing", extra={"error": str(e)})

        # 4) DB insert
        await workflow.execute_activity(
            run_insert_sow,
            args=[input.sow_id, input.filename, pdf_url] + list(sow_fields.values()),
            start_to_close_timeout=timedelta(seconds=30),
        )

        return SowResult(
            status="success",
            step="completed",
            next_action=None,
            sow_fields=sow_fields,
            pdf_url=pdf_url,
        )
```

- **Status** is explicit at each branch (`failed` at `document_intelligence` or `igentic`, or `success` at `completed`).
- **Next action** is set from the workflow (`retry_or_manual`, `manual_review`, or `None` when done).
- You can expose this via Temporal **queries** (e.g. “get current status and next_action”) or by having activities/workflow update a `workflow_status` / `next_action` column in `sow_documents`.

---

## 7. Concrete Steps to Get Started

1. **Set up Temporal**
   - [Install and run Temporal Server](https://docs.temporal.io/self-hosted-guide) (e.g. with Docker), or sign up for [Temporal Cloud](https://temporal.io/cloud).
   - Note the server address and namespace.

2. **Add Temporal SDK to the project**
   - In `AzureFunctions/requirements.txt` add:  
     `temporalio>=1.4,<3`
   - Install in your dev environment and in the worker’s environment.

3. **Create a worker package**
   - e.g. `AzureFunctions/temporal_worker/` with:
     - `workflows/` – e.g. `sow_workflow.py`, `invoice_workflow.py`.
     - `activities/` – thin wrappers that call your existing `shared.helpers` (e.g. `analyze_invoice_bytes`, `process_sow_with_igentic`, `insert_sow`, `upload_file_to_sharepoint`).
     - `worker_main.py` – connect to Temporal, register workflows and activities, run the worker loop.

4. **Keep Azure Functions as the HTTP layer**
   - In `sow_upload/__init__.py`: after validation, instead of calling DI → iGentic → DB directly, use the Temporal **client** to start `SowProcessingWorkflow` with the same inputs you have today (e.g. base64 file, filename, sow_id).
   - Return `workflow_id` (and optionally `run_id`) to the client so they can poll for status (or use webhooks/callbacks if you add them later).

5. **Expose status and next action**
   - **Option 1:** Add a Temporal **query** in your workflow that returns `{ "status": "...", "step": "...", "next_action": "..." }`, and a small Azure Function (e.g. `workflow_status`) that calls the Temporal client to query by `workflow_id` and returns that to the UI.
   - **Option 2:** In your activities (or in the workflow via an “update DB status” activity), write to `sow_documents` / `invoices` (e.g. `workflow_status`, `workflow_step`, `next_action`). Your existing list/detail APIs then show status and you can drive “next action” in the UI from that.

6. **Run the worker**
   - Run the worker process where it can reach Temporal and your DB/APIs (e.g. same VNet as Document Intelligence, iGentic, SharePoint). Start with a single worker; scale later if needed.

---

## 8. Summary

- **Temporal** gives you durable workflows with **status** and **history**, so you can **proceed to the next action based on status** (e.g. retry, manual review, or continue to DB/SharePoint).
- Your **existing steps** (Document Intelligence, iGentic, SharePoint, DB, Excel) become **activities**; the **workflow** encodes the order and the “if status X then do Y” logic.
- **Integration approach:** Azure Functions stay as the HTTP entry point and **start** workflows; a separate **Temporal worker** (Python) runs the workflows and activities. Status/next action can be consumed via Temporal **queries** and/or by storing them in your existing DB for your current UI/APIs.

If you tell me whether you prefer to start with SOW only or with both SOW and Invoice, I can outline the exact activity list and a minimal `worker_main.py` + one workflow file tailored to this repo’s structure.
