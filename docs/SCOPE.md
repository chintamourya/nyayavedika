# **NYAYAVEDIKA — Complete Product Scope & Code Implementation Instructions**

## **1\. Objective**

Update the existing **NyayaVedika** application into a unified, AI-powered justice-support platform with three distinct user portals:

1. **Citizen Door** — Access to Justice  
2. **Advocate Door** — Document Preparation & Case Intelligence  
3. **Court Staff Door** — Court Operations

**Tagline:** One Platform. Three Doors. Timely Justice.

This is an existing application, not a greenfield project. Your responsibility is to inspect the entire existing codebase, understand its architecture and workflows, and implement the agreed product scope while preserving working functionality.

Do not blindly rewrite the application or introduce unnecessary architectural changes.

---

# **2\. Mandatory Instructions Before Development**

Before modifying any code:

1. Inspect the complete repository, including backend, frontend, database models, APIs, authentication, AI agents, document processing, and existing workflows.  
2. Understand how the existing Citizen and Court Staff portals work.  
3. Identify existing reusable modules, endpoints, services, components and utilities.  
4. Identify missing functionality and implementation gaps.  
5. Map each requested feature to existing code or identify the new code required.  
6. Check dependencies, database schemas, deployment configuration and environment variables.  
7. Prepare an implementation plan based on the actual codebase.

Do not duplicate existing functionality.

Do not remove working features simply because a different implementation appears easier.

**Preserve existing business logic unless a change is explicitly required by this scope.**

---

# **3\. Final Product Scope**

## **PORTAL 1: CITIZEN DOOR**

**Purpose: Access to Justice**

Designed for ordinary citizens who need to understand their legal problems, rights and available legal remedies.

The Citizen Door must contain exactly these four main capabilities.

### **3.1 Describe Your Legal Problem**

**Supported legal problem categories:**

* Property and land disputes  
* Family and matrimonial matters  
* Employment and labour issues  
* Consumer complaints  
* Police and criminal matters  
* Government-related grievances  
* Other legal issues

The citizen should be able to describe their problem naturally without knowing the relevant legal terminology.

**Required workflow:**

Step 1 — Understand the problem:

* Accept the citizen's natural-language description.  
* Identify the nature of the legal issue.  
* Extract relevant facts, parties, events and dates.  
* Identify the applicable jurisdiction or ask for missing location information when necessary.  
* Identify the actual legal question or assistance required  
  (Step 1 is one structured-extraction LLM call returning JSON: category, facts, parties, dates, jurisdiction, missing_info, legal_question. Ask a follow-up question if jurisdiction is missing.)

Step 2 — Generate search formulations:

* Generate two differently worded search queries based on the same legal problem.  
* The formulations must improve search coverage rather than simply repeat the original question.  
* Include relevant Indian legal terminology, provisions or jurisdictional terms when supported by the available information.

Step 3 — Search the internet:

* Execute both searches using a real web-search integration.  
* Retrieve relevant legal information dynamically.  
* Do not depend on a custom-built legal knowledge base or manually curated legal database for this feature.  
* Reuse an existing search integration if available.  
* If no suitable integration exists, implement a modular search service using a supported search provider.

Step 4 — Filter and validate sources:

Prioritise authoritative sources:

* India Code  
* Supreme Court of India  
* Relevant High Courts  
* Ministry and government websites  
* National Legal Services Authority (NALSA)  
* State Legal Services Authorities (SLSA)  
* District Legal Services Authorities (DLSA)  
* Other relevant official legal and government portals

Requirements:

* Remove duplicate search results.  
* Filter irrelevant and unreliable sources.  
* Prefer primary legal sources over secondary explanations.  
* Identify conflicting information instead of silently choosing one source.  
* Do not present an unofficial website as an official legal authority.

Step 5 — Generate legal assistance:

Generate a structured, citizen-friendly response containing:

* Understanding of the citizen's problem.  
* Relevant laws and legal provisions.  
* Applicable rights and protections.  
* Possible legal remedies.  
* Relevant authorities or institutions.  
* Availability of free legal aid, where applicable.  
* Practical next steps.  
* Important limitations or missing information.

Step 6 — Display sources:

Every substantive legal answer must include supporting source links.

Display:

* Source title.  
* Source organisation or website.  
* Clickable URL.  
* Relevant provision or supporting information, where available.  
* Retrieval date.  
* Applicable jurisdiction.

**Mandatory safeguards:**

* Never invent legal provisions, court judgments, deadlines or procedures.  
* Never fabricate search results or source URLs.  
* Clearly distinguish verified information from assumptions.  
* If reliable sources cannot be found, explicitly state that.  
* If sources conflict, disclose the conflict.  
* Use plain language understandable to ordinary citizens.  
* Do not present AI-generated output as definitive legal advice.  
* Do not use web research as a substitute for deterministic eligibility rules in the Legal Aid Assistant.

**Important:** This feature must work through live internet research. Do not spend development time building a custom legal database for it.

### **3.2 Legal Aid Assistant**

Preserve and improve the existing implementation.

Required functionality:

* Section 12 legal aid eligibility assessment.  
* Explain eligibility requirements.  
* Answer legal aid-related questions.  
* Explain free legal aid procedures and available assistance.  
* Generate free legal aid application documents.

Implementation requirements:

* Preserve existing deterministic Section 12 eligibility logic.  
* Preserve existing legal aid knowledge resources.  
* Do not replace deterministic eligibility assessment with an LLM decision.  
* Keep application generation functional.  
* Do not introduce legal aid application tracking.

### **3.3 Citizen Document Summary**

Provide a simple document explanation experience for citizens. Implement as a single LLM call over the extracted, page-tagged text.

Required functionality:

* Upload a legal document, notice, court order or other relevant legal document.  
* Extract text using the existing document extraction and OCR pipeline.  
* Explain what the document is about.  
* Identify the parties involved.  
* Explain important facts and dates.  
* Explain the decision, notice or current procedural position, where identifiable.  
* Explain what the citizen should understand.  
* Provide practical next steps where supported by the document.

Output requirements:

* Use simple, non-technical language.  
* Avoid unnecessary legal jargon.  
* Do not invent facts absent from the document.  
* Preserve page references where possible.  
* Clearly indicate when the document does not contain enough information to determine something.

### **3.4 Rights & Legal Information**

**Preserve the existing implementation EXACTLY AS IT EXISTS IN THE CURRENT CODEBASE.**

This is an explicit requirement.

* Do not redesign this feature.  
* Do not replace its existing content.  
* Do not remove existing topics or information.  
* Do not change its underlying logic or data sources.  
* Do not introduce a new knowledge base.  
* Do not merge it into Describe Your Legal Problem.  
* Do not unnecessarily change its UI, APIs or behaviour.

Only make changes if absolutely necessary for compatibility with the updated application. Any such change must preserve existing functionality and content.

---

# **PORTAL 2: ADVOCATE DOOR**

**Purpose: Document Preparation & Case Intelligence**

Designed for advocates who need to prepare, organise and analyse legal documents efficiently.

The Advocate Door must contain exactly two main capabilities.

### **4.1 Document Studio \-** 

CasePDF is a feature reference. Reimplement in this codebase.
Build priority (by value to the Timely Justice theme, see docs/RUBRIC.md): merge, split, OCR, page numbers, bookmarks, clickable index first; rotate, reorder and remove pages last.

Build a CasePDF-inspired document preparation and PDF management experience.

Implement the following capabilities that adds value :

1. Merge multiple PDF documents into one PDF.  
2. Split PDFs into individual documents or volumes.  
3. Reorder PDF pages.  
4. Rotate PDF pages.  
5. Remove selected pages.  
6. OCR scanned PDF documents.  
7. Add bookmarks.  
8. Generate a clickable document index.  
9. Add page numbers.

Requirements:

* Provide an intuitive document upload interface.  
* Allow users to preview and manage pages.  
* Provide clear controls for each supported operation.  
* Preserve original document quality wherever possible.  
* Allow users to download the processed PDF.  
* Handle large documents and processing errors gracefully.  
* Copy no CasePDF source unless its LICENSE is permissive; if you do, credit it in docs/CREDITS.md.

Do not add unrelated document-management or advocate practice-management functionality.

### **4.2 AI Document Insights**

Allow advocates to upload a legal document and generate four different types of AI insights.

The four insight types are:

**A. Issues**

* Identify legal and factual issues arising from the document.  
* Identify questions in dispute.  
* Identify matters requiring determination.  
* Distinguish explicitly stated issues from inferred issues.

**B. Facts**

* Extract material facts.  
* Identify parties and their roles.  
* Extract important events and dates.  
* Organise events chronologically.  
* Preserve supporting page references.

**C. Case Background**

* Explain the nature of the dispute.  
* Describe the circumstances leading to the case.  
* Extract relevant procedural history.  
* Identify the context necessary to understand the matter.

**D. Summarization**

* Generate a comprehensive, structured summary.  
* Include relevant parties, facts, events, claims, arguments, procedural history and decisions where present.  
* Preserve important legal terminology.  
* Maintain the original document's meaning.

**Critical generation behaviour:**

* The advocate uploads a document once.  
* The system extracts its content and performs OCR if required.  
* The advocate selects one of the four insight types.  
* Generate only the selected insight.  
* Do not automatically generate all four insights.  
* If the advocate subsequently selects another insight for the same document, reuse previously extracted text and OCR results.  
* Do not repeat OCR or document extraction unnecessarily.  
* Preserve page references and supporting passages wherever possible.  
* Distinguish source facts from AI-generated inferences.  
* Never invent facts, evidence, legal provisions or case history.  
* Display loading, completion and error states clearly.

**Output style:**

Unlike the Citizen Document Summary, Advocate AI Document Insights must be detailed, structured and suitable for legal professionals.

Do not create a separate legal research module, drafting assistant, client management system or case workspace.

Add faded button multi document insights generation (as if it is coming soon)

---

# **PORTAL 3: COURT STAFF DOOR**

**Purpose: Court Operations**

Preserve the existing Court Staff portal and its seven modules.

Improve the existing implementation, usability, consistency and underlying logic without changing the agreed scope.

The seven modules are:

### **5.1 Today**

* Daily operational dashboard.  
* Pending workload.  
* Important tasks and alerts.  
* Relevant case activity and operational status.

### **5.2 Intake**

* Upload case documents.  
* OCR scanned documents.  
* Extract relevant case information.  
* Validate extracted information.  
* Support case intake workflows.

### **5.3 Docket**

* Case management.  
* Case classification.  
* Case prioritisation.  
* Display important case information and status.  
* Support staff in identifying cases requiring attention.

### **5.4 Cause List**

* Generate hearing lists.  
* Organise cases for scheduling.  
* Support hearing-date and scheduling workflows.  
* Display relevant case and hearing information.  
* Prevent inconsistent or duplicate scheduling.

### **5.5 Undertrial**

* Monitor undertrial prisoner information.  
* Implement Section 479 BNSS monitoring.  
* Calculate relevant detention periods using reliable date and legal-rule logic.  
* Identify potential eligibility for review.  
* Display alerts and supporting information.

The system must flag cases for authorised human review. It must not independently order release or make judicial decisions.

### **5.6 Document Summary**

* Analyse uploaded case documents.  
* Extract relevant information.  
* Generate structured document summaries.  
* Display important facts and case information.  
* Preserve source references wherever possible.

### **5.7 Insights**

* Display case backlog statistics.  
* Show case trends.  
* Provide workload metrics.  
* Show relevant operational indicators.  
* Support court staff in understanding pending cases and operational performance.

**Important:** These seven modules already exist in the product scope. Reuse and improve their current implementation. Do not rebuild them unnecessarily or introduce additional court modules.

---

# **6\. Shared Architecture and Integration**

The three portals must operate as one unified platform.

Do not build three separate backend applications.

Use the existing architecture wherever practical.

### **6.1 Frontend**

Provide three clearly distinguishable role-specific experiences:

* Citizen  
* Advocate  
* Court Staff

The landing page must make these three entry points immediately understandable.

Requirements:

* Consistent design language.  
* Clear navigation.  
* Responsive UI.  
* Accessible layouts.  
* Appropriate terminology for each user group.  
* No unnecessary complexity.  
* Each portal must display only its relevant functionality.

Do not mix advocate tools into the citizen portal or court staff modules into the advocate portal.

### **6.2 Backend**

Use one shared backend with logically separated services and APIs.

Reuse existing modules for:

* Authentication and authorisation.  
* OCR.  
* Document extraction.  
* AI orchestration.  
* Database access.  
* Document storage.  
* Audit logging.  
* Case processing.

Add new services only when the existing implementation cannot reasonably support the required functionality.

### **6.3 Document Processing**

Create or reuse a common document-processing pipeline.

It should support:

* PDF upload.  
* Text extraction.  
* OCR fallback for scanned documents.  
* Page-level text organisation.  
* Metadata extraction.  
* Reuse of extracted content.  
* Secure document storage.

The same underlying extraction infrastructure should support Citizen Document Summary, Advocate AI Document Insights, Document Studio and Court Staff workflows where applicable.

However, each portal must have its own output format and access permissions.

### **6.4 Role-Based Access Control**

Implement and verify resource-level access control.

Roles:

* Citizen  
* Advocate  
* Court Staff

Requirements:

* Users must only access authorised portal functionality.  
* Documents must not become visible to unrelated users.  
* Advocate documents must remain confidential and isolated.  
* Court staff must access only authorised court records.  
* Citizen submissions must not automatically become court cases.  
* Distinguish legal aid applications, grievances, pre-litigation matters and actual court proceedings.  
* Do not rely solely on frontend visibility to enforce permissions. Validate permissions on the backend.

### **6.5 Configuration and Environment Variables**

* Use `.env` for environment-specific configuration and secrets.  
* Do not introduce hardcoded API keys, passwords or credentials.  
* Do not read deployment secrets from `config.py`.  
* Update `.env.example` with required variable names and descriptions.  
* Preserve deployment compatibility with the existing Azure Container Apps environment.  
* Ensure the application starts correctly when deployed.

---

# **7\. UI/UX Requirements**

The application should look and behave like a coherent, professional justice-support platform.

### **Landing Page**

* Clearly introduce NyayaVedika.  
* Present the three entry points.  
* Explain each portal's purpose briefly.  
* Make navigation intuitive.

### **Citizen Portal**

* Simple conversational interface for describing legal problems.  
* Clear distinction between problem assistance and legal aid.  
* Easy document upload and explanation.  
* Accessible language and clear source links.

### **Advocate Portal**

* Professional document workspace.  
* Clear PDF operations.  
* Document preview.  
* Four easily distinguishable AI insight options.  
* Structured, readable legal analysis.

### **Court Staff Portal**

* Preserve the existing seven-module navigation.  
* Improve dashboard clarity.  
* Make operational workflows intuitive.  
* Show the underlying logic behind prioritisation, scheduling and alerts.  
* Avoid hiding important information behind unnecessary interactions.

### **General UI Rules**

* Consistent typography, spacing, colours and components.  
* Responsive desktop and mobile layouts.  
* Meaningful empty, loading, success and error states.  
* Clear validation messages.  
* Avoid decorative features that do not improve usability.  
* Do not create buttons or UI elements that do not perform their advertised actions.

---

# **8\. Technical and Legal Reliability Requirements**

These requirements apply across the application.

1. Do not fabricate legal information, source citations or document facts.  
2. Use deterministic code for calculations and eligibility rules wherever possible.  
3. Use LLMs for extraction, summarisation and language generation, not unsupported legal determinations.  
4. Maintain source traceability for generated document insights.  
5. Preserve document page references wherever technically possible.  
6. Clearly distinguish extracted information, inferred information and external research.  
7. Handle missing, conflicting and incomplete information explicitly.  
8. Do not allow AI-generated output to automatically make consequential judicial decisions.  
9. Ensure all important actions are logged appropriately.  
10. Protect uploaded documents and sensitive case information.

---

# **9\. Explicitly Out of Scope**

Do not implement the following:

* Legal aid application tracking.  
* Advocate CRM.  
* Client management.  
* Advocate calendar or appointment management.  
* Drafting assistant.  
* Separate advocate legal research module.  
* Payment gateway.  
* Consultation marketplace.  
* Video consultation.  
* Custom legal database for Describe Your Legal Problem.  
* Additional court staff modules.  
* Unrequested features that expand the project scope.

Do not introduce these features under different names.

---

# **10\. Testing and Acceptance Criteria**

The implementation is not complete merely because the UI renders.

Test the actual end-to-end workflows.

### **Citizen Door**

* Citizen can describe a legal problem.  
* System generates two search formulations.  
* Both searches execute successfully.  
* Results are filtered and grounded in retrieved sources.  
* The answer displays clickable sources.  
* Unsupported claims are not fabricated.  
* Legal Aid Section 12 assessment continues to work.  
* Legal aid application generation works.  
* Citizen Document Summary works.  
* Rights & Legal Information remains unchanged in functionality and content.

### **Advocate Door**

* Advocate can access the portal.  
* Advocate can upload a PDF.  
* All specified Document Studio operations work.  
* Processed documents can be downloaded.  
* AI Document Insights supports all four insight types.  
* Only the selected insight is generated.  
* Subsequent insights reuse extracted text and OCR results.  
* Page references are retained wherever possible.  
* Advocate documents are not accessible to unauthorised roles.

### **Court Staff Door**

* All seven existing modules remain accessible.  
* Intake and OCR workflows work.  
* Docket classification and prioritisation work.  
* Cause List generation works.  
* Section 479 BNSS monitoring works with test cases.  
* Document Summary works.  
* Insights display consistent metrics.  
* Existing workflows are not broken by the changes.

### **Platform**

* All three portals work through the shared backend.  
* Authentication and backend authorisation work.  
* Cross-role data access is restricted.  
* Existing database records remain compatible.  
* No broken routes, APIs or frontend interactions.  
* No missing dependencies or configuration variables.  
* Application starts successfully.  
* Application is deployable to the existing Azure environment.

---

# **11\. Development Execution Instructions**

Follow this implementation sequence:

**Phase 1 — Codebase assessment**

* Inspect the complete repository.  
* Map existing features and architecture.  
* Identify reusable code and missing functionality.

**Phase 2 — Platform and navigation**

* Implement the three-door landing page.  
* Add or improve role-specific navigation.  
* Preserve existing authentication.

**Phase 3 — Citizen Door**

* Merge Describe Your Problem and Web-based Legal Assistance into one feature.  
* Implement the two-formulation live web research workflow.  
* Preserve and improve Legal Aid Assistant.  
* Implement or improve Citizen Document Summary.  
* Preserve Rights & Legal Information exactly as it is.

**Phase 4 — Advocate Door**

* Implement the CasePDF-inspired Document Studio.  
* Implement the four on-demand AI Document Insights.  
* Reuse the existing document extraction and OCR infrastructure.

**Phase 5 — Court Staff Door**

* Preserve and improve the seven existing modules.  
* Fix logical, functional and UI issues.  
* Ensure all existing workflows continue working.

**Phase 6 — Integration**

* Connect all portals to the shared backend.  
* Implement and verify role-based permissions.  
* Ensure document processing is reusable.

**Phase 7 — Testing and deployment**

* Run backend tests.  
* Test frontend workflows.  
* Test APIs and permissions.  
* Test document processing.  
* Test real user journeys for all three roles.  
* Fix identified issues.  
* Verify deployment compatibility.

---

# **12\. Final Instructions to the Coding Agent**

This is a complete product update, not a request to create a prototype or static UI.

You must implement the actual backend logic, APIs, frontend interactions, data handling and integrations required by the scope.

**Non-negotiable constraints:**

1. Work on the existing codebase.  
2. Preserve existing working functionality.  
3. Preserve Rights & Legal Information exactly as currently implemented.  
4. Do not create duplicate modules for functionality that already exists.  
5. Do not add features outside the agreed scope.  
6. Do not use mock data as a substitute for actual functionality, except in explicitly isolated demo/test scenarios.  
7. Do not fabricate successful AI, search, OCR or document-processing results.  
8. Do not silently swallow errors.  
9. Do not leave non-functional buttons, placeholder pages or incomplete API integrations.  
10. Do not compromise role-based data isolation.  
11. Keep the application deployable in its existing environment.  
12. Do not stop after producing an implementation plan. Complete the implementation.

When finished, provide:

* Summary of implemented changes.  
* New and modified files.  
* New and modified API endpoints.  
* Database schema or migration changes.  
* External integrations and required environment variables.  
* Tests executed and their results.  
* Known limitations or incomplete items.

If a feature cannot be implemented because a required external service, credential or dependency is unavailable, identify the exact blocker. Do not pretend it is complete.

**Final success criterion:** NyayaVedika must operate as one integrated platform with three functional portals: Citizen, Advocate and Court Staff. All agreed features must work, existing functionality must be preserved, and no unrequested modules should be introduced.