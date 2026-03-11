
# S3 Services

This is the list of S3 services required in Phase I.

## I. AnswerService:
	A. Upsert answer for a question
	B. View answer for a question

### Clarification:
[Q1] When does an answer move from draft → submitted?
  - Yes, explicit call.
[Q2] Can users edit a submitted answer?
  - Yes, they can edit as long as it is in `draft`


## II. AuditoService:
	A. View answers for all answered questions for a given org_id
	B. Update 'auditor_feedback' for a given "question_id"

### Clarification:
[Q3] Can auditor review?
  - Well, the idea is to review only post the AI-process (but it may change in the future)
[Q4] Can auditor update feedback multiple times per question?
  - Nope, only once


### III. AIServices:
	A. Call ai service for a given org_id (and question_id optional)

### Clarification:
[Q5] When AIServices is called? 
  - Process all pending questions that are in submitted status and based on `version` not processed before
[Q6] Should AI run if status in `draft`?
  - No, it should not

### IV. ReportService:
	A. Data for dashbaord covering 
		- # auditors
		- # organization for each auditor
		- Details on audit_completion, review_status, etc.,
	B. Fetch gap_analysis report for a given org_id	

### Clarification:
[Q7] For dashboard: real-time accuracy (compute from S3 each time), or cached?
  - For now, real-time. Will enhance in phase II to cache it

[Q8] "# auditors" and "org per auditor":
  - In S3, for now, the `auditor_master` should store auditor details and optionally the `organizations` mapped to each auditor 


### V. OperationalService:
	A. List all lookup data (org_id, domain)
	A2. Let of unique org_ids - pre-requsite for IV [B] 
	B. Get org_id for a given domain
	C. Add/Edit/Remove auditors (maintain auditor_master)
	D. Assign auditor to Organization
	
### Clarification:
[Q9] Auditor Master Structure (suggested):
{
   auditor_id: "1",
      name: "John Smith",
      email: "...",
      region: "EMEA",
      organizations: [],
      enrolled: "2024-12-10",
}

[Q10] Org ↔ Auditor mapping:
  - 1 org to 1 auditor
  - 1 auditor will have many orgs


### Other Clarifications:

[Q11] For "View answers for all questions": Response include only answer
[Q12] If data missing: Only answer is required
[Q13] Since no Redis: Are we okay with `last write wins`? Yes
[9] Naming Consistency: That was my typo `AuditorService` is correct
