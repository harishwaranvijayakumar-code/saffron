# Saffron - Intelligence in Motion

### Governed Workflow Execution and Evidence-Driven Automation

**Saffron** is a Django-based workflow platform designed to make automated work explicit, controlled, observable, and recoverable.

Its built-in AI assistant, **Dune**, helps prepare workflow plans. Saffron provides the surrounding application structure for reviewing those plans, confirming intent, enforcing authorization boundaries, coordinating execution, tracking lifecycle state, and preserving evidence about the outcome.

**Live application:** [Saffron on Render](https://saffron-lp0q.onrender.com)

**Source repository:** [harishwaranvijayakumar-code/saffron](https://github.com/harishwaranvijayakumar-code/saffron)

**Production database:** Neon PostgreSQL

**Application hosting:** Render

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Project Thesis](#project-thesis)
3. [The Problem Saffron Addresses](#the-problem-saffron-addresses)
4. [What Saffron Is](#what-saffron-is)
5. [What Saffron Is Not](#what-saffron-is-not)
6. [Core Design Principles](#core-design-principles)
7. [System Capabilities](#system-capabilities)
8. [The Role of Dune](#the-role-of-dune)
9. [Workflow Lifecycle](#workflow-lifecycle)
10. [Plan Confirmation](#plan-confirmation)
11. [Authorization and Approval Boundaries](#authorization-and-approval-boundaries)
12. [Execution Gateway](#execution-gateway)
13. [Execution Adapters](#execution-adapters)
14. [Simulation and Live Execution](#simulation-and-live-execution)
15. [GitHub Integration](#github-integration)
16. [Lifecycle State and Recovery](#lifecycle-state-and-recovery)
17. [Leases and Concurrent Execution](#leases-and-concurrent-execution)
18. [Audit Trail and Evidence](#audit-trail-and-evidence)
19. [Failure Handling](#failure-handling)
20. [Idempotency and Retries](#idempotency-and-retries)
21. [System Architecture](#system-architecture)
22. [Component Responsibilities](#component-responsibilities)
23. [Request and Execution Data Flow](#request-and-execution-data-flow)
24. [Data Persistence](#data-persistence)
25. [Database Design Considerations](#database-design-considerations)
26. [Technology Stack](#technology-stack)
27. [Repository Structure](#repository-structure)
28. [Configuration and Environment Variables](#configuration-and-environment-variables)
29. [Local Development](#local-development)
30. [Database Setup](#database-setup)
31. [Running the Application](#running-the-application)
32. [Testing Strategy](#testing-strategy)
33. [Verification Commands](#verification-commands)
34. [Production Deployment](#production-deployment)
35. [Render Configuration](#render-configuration)
36. [Neon PostgreSQL Configuration](#neon-postgresql-configuration)
37. [Health and Readiness Checks](#health-and-readiness-checks)
38. [Database Migrations](#database-migrations)
39. [GitHub Credentials and Repository Allowlisting](#github-credentials-and-repository-allowlisting)
40. [Security Model](#security-model)
41. [Data Privacy](#data-privacy)
42. [Operational Observability](#operational-observability)
43. [Reliability Invariants](#reliability-invariants)
44. [Testing Live Integrations Safely](#testing-live-integrations-safely)
45. [Troubleshooting](#troubleshooting)
46. [Known Limitations](#known-limitations)
47. [Engineering Roadmap](#engineering-roadmap)
48. [Project Verification Record](#project-verification-record)
49. [Engineering Methodology](#engineering-methodology)
50. [Final Project Thesis](#final-project-thesis)

---

# 1. Project Overview

Saffron explores a practical problem in workflow automation.

Automated systems can prepare plans, invoke APIs, and report results. However, a dependable workflow platform must also distinguish between proposed work, authorized work, attempted work, and verified outcomes.

Saffron is designed around that distinction.

The application provides a web interface for working with workflow runs and plans. Its execution architecture separates workflow coordination from the adapters that perform operations.

The built-in assistant, Dune, supports the planning side of this process.

The application remains responsible for the execution controls surrounding a plan.

## 1.1 Project Identity

| Property | Value |
|---|---|
| Project name | Saffron |
| Built-in assistant | Dune |
| Primary language | Python |
| Web framework | Django |
| Application server | Gunicorn |
| Database | PostgreSQL in production |
| Database provider | Neon |
| Application hosting | Render |
| Static asset handling | WhiteNoise |
| Test framework | pytest |
| Django test integration | pytest-django |
| Primary repository | GitHub |
| Main branch | `main` |

## 1.2 Live Application

The deployed application is available at:

[https://saffron-lp0q.onrender.com](https://saffron-lp0q.onrender.com)

The deployment exposes a health endpoint and a database readiness endpoint.

These endpoints support operational verification, but they do not establish that every workflow or external integration has been tested.

## 1.3 Project Objective

The objective is to build a workflow platform where automation can be inspected and controlled.

Saffron emphasizes:

- Explicit workflow intent.
- Deliberate plan confirmation.
- Authorization before consequential actions.
- A controlled execution boundary.
- Adapter isolation.
- Lifecycle tracking.
- Lease and recovery behavior.
- Audit information.
- Evidence about execution outcomes.
- Testable failure handling.
- Explicit configuration of live integrations.
- Separation between simulated and real operations.

The project is not intended to make every operation autonomous.

It is intended to make the operations that are supported easier to govern.

---

# 2. Project Thesis

A proposed action is not an authorized action.

An authorized action is not necessarily a successfully completed action.

A successfully completed request is not necessarily proof that the intended external outcome occurred.

These distinctions matter when a workflow can affect an external system.

Consider the following conceptual workflow:

```text
A user requests work.
        |
        v
Dune helps prepare a plan.
        |
        v
The plan is presented for review.
        |
        v
The workflow confirms the required authorization.
        |
        v
The execution gateway coordinates the operation.
        |
        v
An adapter performs or simulates the action.
        |
        v
The workflow records the outcome.
        |
        v
An operator inspects the evidence.
```

Every transition has a different responsibility.

Planning concerns intent.

Confirmation concerns whether the proposed plan should proceed.

Authorization concerns whether the operation is permitted.

Execution concerns the actual attempt to perform work.

Evidence concerns what can be established about the attempt and its outcome.

Recovery concerns how the system behaves when execution is interrupted or fails.

Saffron is organized around these responsibilities rather than treating automation as a single uninterrupted function call.

## 2.1 The Central Distinction

A plan describes what should happen.

A policy determines what is permitted.

An execution gateway coordinates how an operation is carried out.

An adapter communicates with the relevant implementation or external system.

An audit record preserves information about the workflow.

Evidence helps an operator evaluate what occurred.

These responsibilities are related, but they are not interchangeable.

## 2.2 Why the Distinction Matters

Suppose an assistant proposes an operation against a GitHub repository.

The proposal may be valid.

The repository may be on an allowlist.

The configured credential may permit read access.

None of these facts automatically authorizes every possible write operation.

A read-only workflow-run query and a write operation such as creating an issue comment have different consequences.

Saffron therefore treats live reads and external writes as separate capabilities.

The current GitHub integration uses controlled live reads when enabled and retains simulated, approval-gated issue-comment creation.

## 2.3 Evidence Before Confidence

A workflow result should not be trusted merely because the application returned a successful HTTP response.

An external operation may time out after the remote service has already accepted it.

A worker may stop before saving the result.

A retry may encounter an operation that was already performed.

An adapter may return simulated output rather than evidence of a real external change.

The application must preserve the distinction between what was requested, what was attempted, and what was observed.

This principle informs the design and testing of Saffron.

---

# 3. The Problem Saffron Addresses

Workflow automation introduces coordination problems that are easy to overlook when focusing only on the API call.

## 3.1 Intent and Execution Can Diverge

A plan can describe an operation that the application must not execute.

The operation may require confirmation.

The current configuration may disable the adapter.

The target may fall outside the repository allowlist.

The credential may lack the required permission.

The workflow may have expired or become invalid.

A dependable system needs a way to reject or stop work when its assumptions are no longer satisfied.

## 3.2 External Operations Can Fail Independently

A workflow may depend on several systems.

The application may be available while GitHub is unavailable.

The database may be healthy while an external API times out.

An adapter may return a valid response while a later persistence operation fails.

These failures have different meanings and require different handling.

## 3.3 Retries Can Be Dangerous

A retry may be harmless for a read-only request.

A retry may be consequential for an external write.

If a request times out, the caller may not know whether the remote system accepted it.

Blindly repeating the operation can produce duplicate effects.

Saffron's execution design therefore needs to consider retries, idempotency, and uncertain outcomes separately.

## 3.4 State Must Remain Inspectable

A workflow should not disappear from the operator's view merely because an execution attempt failed.

Useful records can include:

- The workflow identity.
- The requested operation.
- The plan that was confirmed.
- The applicable authorization decision.
- The execution attempt.
- The adapter outcome.
- The lifecycle transition.
- The failure classification.
- The evidence available to support the result.

The precise record depends on the implemented data model.

The principle is to preserve enough information to investigate the outcome without inventing certainty.

## 3.5 Recovery Must Be Deliberate

Recovery is not simply changing a failed status back to a pending status.

The system must consider whether the operation started.

It must consider whether a lease expired.

It must consider whether another worker has taken responsibility.

It must consider whether an external side effect may already have happened.

Recovery should preserve the distinction between retryable failures and uncertain external outcomes.

---

# 4. What Saffron Is

Saffron is a Django workflow platform with an AI-assisted planning component and controlled execution architecture.

Its purpose is to provide a structured path from a proposed plan to an inspectable execution outcome.

## 4.1 A Workflow Application

Saffron provides web-facing workflow functionality.

The application includes a home page, authentication routes, a dashboard, workflow-run creation, run detail views, and plan confirmation routes.

The deployed health and readiness endpoints provide basic operational checks.

## 4.2 An Execution Coordination Layer

Saffron separates workflow coordination from external execution.

An execution gateway provides a controlled boundary for invoking supported operations.

The gateway and adapter architecture allows simulated behavior and optional live integration behavior to be configured separately.

## 4.3 An AI-Assisted Planning Workflow

Dune is the built-in assistant.

Its role is associated with preparing and shaping plans.

The surrounding application remains responsible for enforcing the execution rules that apply to a plan.

The presence of an AI assistant does not imply unrestricted authority to execute arbitrary operations.

## 4.4 A Platform for Controlled Integration

Saffron includes a simulator and an optional GitHub read adapter.

Live GitHub reads can be controlled by configuration and an explicit repository allowlist.

The current write-related behavior remains simulated and approval-gated.

## 4.5 A System Under Active Engineering

Saffron is an evolving project.

Capabilities should be documented according to the implementation and verification evidence available at the time of release.

A planned feature is not a completed feature.

A passing unit test is not a complete production integration test.

A healthy web process is not proof of end-to-end correctness.

---

# 5. What Saffron Is Not

Saffron should not be understood as an unrestricted autonomous agent.

It is not a guarantee that every proposed plan is safe.

It is not a replacement for authorization policy.

It is not a guarantee that an external API will behave correctly.

It is not a universal workflow engine for every external service.

It is not a guarantee that every failed operation can be rolled back.

It is not a substitute for operational monitoring.

It is not a reason to grant broad credentials to an automation system.

It is not a claim that simulated output represents an actual external side effect.

It is not a guarantee that an AI-generated plan is complete or correct.

It is not a claim that all possible failure states have been eliminated.

These boundaries are intentional.

A workflow platform is more useful when its guarantees are clearly defined than when it claims capabilities that have not been demonstrated.

---

# 6. Core Design Principles

## 6.1 Intent Is Not Permission

A user request expresses intent.

A plan organizes that intent into proposed work.

The plan must still pass through the required confirmation and authorization boundaries.

## 6.2 Confirmation Is a Distinct Step

Confirmation should be distinguishable from plan generation.

The system should not silently treat a generated plan as if a user had approved it.

## 6.3 External Operations Need Controls

An adapter should not become an unrestricted path around the execution policy.

Supported operations should be invoked through the intended application boundaries.

## 6.4 Simulation Must Be Explicit

A simulated operation is useful for testing.

It can validate workflow coordination without changing an external system.

The application should not describe simulated behavior as a completed real-world write.

## 6.5 Failures Are Normal Operating Conditions

Network failures, process interruptions, invalid input, database errors, and remote API failures are normal possibilities.

The workflow must have a defined response to them.

## 6.6 Recovery Must Respect Uncertainty

An expired lease does not prove that the previous operation had no effect.

A timeout does not prove that a remote operation failed.

Recovery must account for uncertain outcomes rather than assuming that all failures are safe to retry.

## 6.7 Evidence Must Remain Distinguishable from Interpretation

A recorded response is evidence of a response.

A successful read is evidence of data retrieval.

A simulated result is evidence that a simulation path ran.

These facts do not automatically establish that an external write occurred.

## 6.8 Configuration Should Be Explicit

Live integrations should not become active accidentally because a developer environment happens to contain a credential.

Feature flags, repository allowlists, and credentials should be configured deliberately.

## 6.9 Least Privilege Is Preferable

Credentials should grant only the permissions needed for the configured operation.

A read-only workflow should not require an unnecessarily broad write credential.

## 6.10 Tests Should Cover Failure Paths

Testing only successful requests leaves important execution behavior unverified.

Tests should include invalid inputs, denied operations, unavailable dependencies, expired leases, and interrupted execution where applicable.

## 6.11 Deployment Health Is Not Complete Verification

The application may pass a health check while a workflow route is broken.

The database may be reachable while a required migration is missing.

The site may be available while a GitHub integration is misconfigured.

Deployment validation should test each important boundary separately.

---

# 7. System Capabilities

This section describes the main capability areas of Saffron without implying that every possible adapter or workflow operation is supported.

## 7.1 Workflow Run Management

The application provides a workflow-run interface.

The relevant routes include the dashboard, run creation, run detail, and plan confirmation.

These routes provide the web-facing structure for interacting with workflow records.

## 7.2 Plan Preparation

Dune supports the planning side of the system.

The proposed plan must remain separate from authorization and execution.

## 7.3 Plan Confirmation

The workflow includes a confirmation route.

Confirmation is a meaningful boundary in the execution lifecycle.

## 7.4 Controlled Execution

The execution gateway provides a central coordination point for supported operations.

This makes it possible to separate workflow rules from the implementation details of individual adapters.

## 7.5 Simulated Operations

The simulator allows workflow behavior to be exercised without implying that a real external action occurred.

Simulation is useful for regression testing and development.

## 7.6 Optional GitHub Reads

The GitHub adapter can retrieve workflow-run information from allowlisted repositories when live reads are enabled.

This capability is controlled by environment configuration.

## 7.7 Database Persistence

Saffron uses Django's ORM and a PostgreSQL production database.

The application includes database migrations and a readiness endpoint that verifies database connectivity.

## 7.8 Health and Readiness

The `/health/` endpoint checks application responsiveness.

The `/ready/` endpoint checks whether the application can reach its configured database.

These checks answer different operational questions.

## 7.9 Automated Tests

The project uses pytest and pytest-django.

The test suite covers workflow behavior and integration-related components.

The recorded local verification reached 136 passing tests with live GitHub reads disabled.

That result is specific to the recorded test session.

---

# 8. The Role of Dune

Dune is Saffron's built-in AI assistant.

Its role is to help with workflow planning.

The application provides the surrounding controls needed to turn a proposal into a governed workflow.

## 8.1 Planning Assistance

An assistant can help translate a request into structured proposed work.

The result may be useful without being ready for execution.

The plan should remain available for review.

## 8.2 Plan Quality

An AI-generated plan may contain incomplete assumptions.

It may misunderstand the requested scope.

It may omit a required dependency.

It may propose an operation that is not supported by the configured adapter.

It may need revision before confirmation.

These possibilities are reasons to preserve a review boundary.

## 8.3 Planning and Authorization

Dune's planning role should not be interpreted as blanket authority to perform external actions.

The application's authorization and approval controls remain important.

## 8.4 Planning and Execution

A proposed operation is not proof that the operation was attempted.

An attempted operation is not proof that the external system accepted it.

An accepted operation is not necessarily proof that every intended downstream effect occurred.

The system should preserve these distinctions in its workflow records and operator-facing messages.

## 8.5 Assistant Limitations

The presence of an assistant does not eliminate the need for:

- Input validation.
- Authorization checks.
- Policy enforcement.
- Safe adapter behavior.
- Failure handling.
- Audit information.
- Operational verification.

The assistant is one component in the workflow, not a replacement for the workflow's control plane.

---

# 9. Workflow Lifecycle

A workflow moves through a series of meaningful states and transitions.

The exact state names and transition rules are defined by the application implementation.

The following diagram represents the conceptual lifecycle rather than a complete enumeration of the model's persisted statuses.

```text
             Request received
                    |
                    v
             Plan prepared
                    |
                    v
           Plan review and edit
                    |
                    v
              Confirmation
                    |
                    v
        Authorization and policy
                    |
          +---------+---------+
          |                   |
          v                   v
      Authorized           Rejected
          |
          v
     Execution attempt
          |
     +----+----------------+
     |                     |
     v                     v
  Succeeded              Failed
     |                     |
     v                     v
  Evidence             Failure review
     |                     |
     v                     v
  Complete          Recovery decision
```

This conceptual model does not imply that every state is stored as a separate database value.

## 9.1 Request Intake

The workflow begins with a request or an existing plan.

The request should be represented in a form that the application can validate and process.

## 9.2 Plan Preparation

The proposed work is assembled.

The plan may include one or more intended operations.

The plan should not bypass later authorization checks.

## 9.3 Review

The plan can be reviewed before proceeding.

Review is particularly important when the operation can affect an external system.

## 9.4 Confirmation

The application provides a distinct plan-confirmation route.

The confirmation step should be interpreted according to the actual workflow rules.

## 9.5 Authorization

The application evaluates the relevant permission and policy requirements.

An operation that is not permitted should not proceed merely because it appears in a plan.

## 9.6 Execution

The execution gateway coordinates the operation.

The selected adapter determines whether the operation is simulated or interacts with an external service.

## 9.7 Result Recording

The workflow records the outcome according to the application's persistence model.

The recorded outcome should not claim more than the adapter response supports.

## 9.8 Completion

Completion should represent the workflow's defined success condition.

It should not be used as a vague substitute for an unknown external outcome.

## 9.9 Recovery

Recovery requires an explicit decision about whether the operation can safely be retried or needs further investigation.

An uncertain external side effect must not be treated as if it definitely did not occur.

---

# 10. Plan Confirmation

Plan confirmation is an important boundary between proposing work and proceeding with it.

## 10.1 Why Confirmation Matters

A plan may contain operations that have consequences outside the application.

Review gives the operator an opportunity to inspect the proposed scope.

Confirmation records the decision to proceed according to the application's workflow rules.

## 10.2 Confirmation Is Not Universal Authorization

Confirmation should not be interpreted as permission to ignore other policy requirements.

An operation may still be rejected by an authorization check.

A repository may not be allowlisted.

An adapter may be disabled.

A required credential may be unavailable.

The application should retain the controls that apply after confirmation.

## 10.3 Confirmation and Plan Changes

If a plan changes materially after confirmation, the application should not silently assume that the previous decision covers every new operation.

The exact implementation should define how plan revisions and confirmation are associated.

## 10.4 Confirmation and Audit

Where supported by the data model, the system should preserve enough information to distinguish:

- The proposed plan.
- The confirmed plan.
- The time or sequence of confirmation.
- The operation subsequently attempted.
- The resulting outcome.

This information makes workflow behavior easier to inspect.

## 10.5 Confirmation Failure

If confirmation fails, the application should return a controlled response.

It should not execute the operation simply because the confirmation request was received.

---

# 11. Authorization and Approval Boundaries

Authorization determines whether a requested operation is permitted.

Approval is a workflow decision required for certain operations.

They are related but not identical.

## 11.1 Authorization

Authorization can depend on the operation, its target, the configured adapter, and the applicable policy.

An operation should not gain additional permissions merely because it was proposed by an assistant.

## 11.2 Approval

Some operations require explicit approval before they can proceed.

Approval should remain associated with the operation or workflow scope it authorizes.

A generic approval should not automatically authorize unrelated future operations.

## 11.3 Repository Allowlisting

The GitHub integration uses a repository allowlist.

The allowlist limits the repositories that the configured live-read integration is intended to access.

It should not be treated as a substitute for credential permissions or operation-level checks.

## 11.4 Feature Flags

`SAFFRON_ENABLE_REAL_GITHUB_READS` controls whether the live GitHub read path is enabled.

The flag should remain disabled until the hosted configuration and intended behavior have been verified.

## 11.5 Write Operations

Live read access and write access are different capabilities.

The current issue-comment creation path remains simulated and approval-gated.

A successful read test does not establish that a write operation is implemented safely.

## 11.6 Fail Closed

When a required authorization decision cannot be established, the system should avoid assuming permission.

The exact behavior should be defined and tested for the relevant execution path.

## 11.7 Authorization Testing

Tests should cover both permitted and denied operations.

They should verify that a denied operation does not reach an external adapter when the policy requires rejection before dispatch.

They should also verify that the denial is observable to the caller or operator.

---

# 12. Execution Gateway

The execution gateway is the central boundary between workflow coordination and operation-specific execution.

## 12.1 Purpose

The gateway provides a controlled place to coordinate supported operations.

It separates workflow intent from the adapter implementation.

It also gives the application a consistent place to apply relevant execution rules.

## 12.2 Gateway Responsibilities

Depending on the specific operation, gateway responsibilities may include:

- Accepting a structured execution request.
- Checking the relevant workflow context.
- Applying execution constraints.
- Selecting an appropriate adapter.
- Coordinating the attempt.
- Handling adapter responses.
- Returning a structured result.
- Supporting lifecycle and recovery behavior.

The exact implementation remains authoritative.

## 12.3 Adapter Separation

The gateway should not need to contain every external API detail.

Adapter-specific behavior belongs in the corresponding adapter layer.

This separation improves testability and limits the spread of external-system assumptions through the workflow code.

## 12.4 Simulation

The gateway and adapter configuration should make simulated behavior distinguishable from live behavior.

The result should not falsely claim that a remote operation occurred.

## 12.5 Failure Responses

The gateway must account for adapter errors.

An adapter may reject a request.

A remote service may be unavailable.

A request may time out.

The application may lose its connection to the database.

These failures should not be collapsed into one misleading success or failure message.

## 12.6 Gateway Testing

Tests should cover:

- Valid execution requests.
- Invalid execution requests.
- Disabled integrations.
- Repository allowlist violations.
- Simulated operations.
- Adapter errors.
- Uncertain remote outcomes.
- Lifecycle updates.
- Authorization denials.

The precise cases should reflect the current implementation and its supported operations.

---

# 13. Execution Adapters

An adapter isolates the details of communicating with a specific execution mechanism.

Saffron includes a simulator and an optional GitHub adapter.

## 13.1 Simulator

The simulator provides a controlled way to exercise workflow behavior.

It can be used during development and testing without asserting that an external side effect occurred.

Simulation is particularly useful when testing lifecycle behavior, error handling, and approval boundaries.

## 13.2 GitHub Adapter

The GitHub adapter supports configured read operations for workflow-run information.

Live reads are subject to feature-flag configuration and repository allowlisting.

The adapter should not be treated as a universal GitHub automation implementation.

## 13.3 Adapter Inputs

An adapter should receive the structured operation it is intended to perform.

It should not silently broaden the operation's scope.

The gateway and authorization logic remain responsible for the relevant controls.

## 13.4 Adapter Outputs

The output should describe the result that the adapter can establish.

A simulated result should remain identifiable as simulated.

A remote read response should remain identifiable as a read result.

An error should not be converted into a successful result merely to keep the workflow moving.

## 13.5 Adapter Isolation

Adapters should be tested independently where possible.

Gateway tests can then verify the coordination behavior without depending on live external services.

## 13.6 Adding an Adapter

A new adapter should have a clear contract.

The contract should define:

- Supported operations.
- Input validation.
- Required permissions.
- Configuration requirements.
- Failure behavior.
- Timeout behavior.
- Retry safety.
- Result representation.
- Evidence requirements.
- Testing strategy.

A new adapter should not become live until its behavior has been reviewed and verified.

---

# 14. Simulation and Live Execution

Simulation and live execution serve different purposes.

They should remain clearly distinguishable.

## 14.1 Why Simulation Exists

Simulation allows developers to exercise application logic without necessarily contacting an external service.

It can validate that a workflow request reaches the intended execution path.

It can validate lifecycle transitions.

It can validate how results are recorded.

It can validate how failures are presented.

## 14.2 Simulation Is Not a Remote Side Effect

A simulated issue-comment creation is not proof that a comment was posted to GitHub.

A simulated execution result is not evidence that a remote system changed.

The application's records and messages should preserve this distinction.

## 14.3 Live Reads

Live GitHub reads are an optional capability.

The feature flag and repository allowlist must be configured deliberately.

The configured credential must have only the required permissions.

## 14.4 Live Writes

Live writes carry different risks from live reads.

They may create, modify, or remove external state.

The current issue-comment creation behavior remains simulated and approval-gated.

This README does not claim that live issue-comment creation is enabled.

## 14.5 Testing Mode

Tests should normally run with live GitHub reads disabled.

An integration test that intentionally contacts GitHub should be clearly separated from ordinary unit and regression tests.

## 14.6 Mode Verification

Before interpreting an integration result, verify whether the operation ran in simulation or live mode.

The result's mode is part of its meaning.

---

# 15. GitHub Integration

Saffron includes an optional GitHub integration for workflow-run information.

The integration is constrained by configuration and repository allowlisting.

## 15.1 Supported Scope

The currently established integration scope includes read operations related to GitHub Actions workflow runs and jobs.

The application has previously been verified against a real GitHub workflow-run read.

That historical integration check does not guarantee that every repository, workflow, or deployment configuration will succeed.

## 15.2 Repository Allowlist

The intended repository allowlist is configured through:

`GITHUB_ALLOWED_REPOSITORIES`

The currently intended repository is:

`harishwaranvijayakumar-code/indexforge`

Only configure repositories that the application is explicitly intended to access.

## 15.3 Feature Flag

Live reads are controlled through:

`SAFFRON_ENABLE_REAL_GITHUB_READS`

Keep this value set to `false` until the hosted configuration has been verified.

## 15.4 GitHub Token

The credential is supplied through:

`GITHUB_TOKEN`

Configure it through the hosting provider's private environment-variable settings.

Do not place the token in source control.

Do not put it in the README.

Do not include it in diagnostic output.

## 15.5 Least-Privilege Permissions

The token should have only the permissions required for the configured read operations.

A workflow-run read does not justify granting broad repository write access.

## 15.6 Error Handling

The integration may encounter:

- Authentication failures.
- Authorization failures.
- Repository allowlist violations.
- Missing workflow runs.
- Missing jobs.
- Rate limits.
- Network errors.
- Remote service errors.
- Invalid response data.

The application should distinguish these conditions where the implementation supports that distinction.

## 15.7 Issue-Comment Creation

Issue-comment creation remains simulated and approval-gated in the current configuration.

Do not infer that live write access is available merely because the GitHub read adapter works.

## 15.8 Safe Verification

Start with a non-destructive read against the explicitly allowed repository.

Verify that the returned result is genuinely from the live integration.

Keep the test isolated from operations that modify external state.

---

# 16. Lifecycle State and Recovery

Workflow execution involves a sequence of transitions.

The application needs to preserve enough state to distinguish active work from completed, failed, or recoverable work.

## 16.1 Lifecycle State

The precise persisted states are defined by the application.

The conceptual lifecycle includes planning, confirmation, execution, result recording, and completion or failure handling.

## 16.2 Valid Transitions

Not every state transition should be permitted.

For example, a terminal state should not silently return to an active state without an explicit recovery or retry decision.

The implementation should define which transitions are valid.

## 16.3 Interrupted Execution

A process can stop after starting an operation but before recording the outcome.

The database may contain an incomplete execution record.

The remote service may already have processed the request.

Recovery must account for these possibilities.

## 16.4 Recovery Decisions

Recovery should consider:

- Whether the operation started.
- Whether the attempt has a recorded outcome.
- Whether the lease is still valid.
- Whether another worker owns the execution.
- Whether the operation is safe to repeat.
- Whether the external outcome is uncertain.
- Whether operator intervention is required.

## 16.5 Recovery and External Systems

The application cannot guarantee that every external side effect can be rolled back.

An operation that created a remote resource may require a separate compensating operation.

A compensating operation may itself fail.

Recovery should not imply stronger guarantees than the external system provides.

## 16.6 Recovery Testing

Tests should cover interrupted and incomplete workflows where the implementation supports them.

They should verify that recovery does not silently bypass authorization.

They should verify that repeated execution does not happen without the required checks.

---

# 17. Leases and Concurrent Execution

Leases can help coordinate ownership of work.

They are useful when execution may be performed by workers or processes that do not share in-memory state.

## 17.1 Lease Purpose

A lease represents a time-bounded claim to perform a piece of work.

It can help prevent multiple workers from treating the same workflow as independently owned.

## 17.2 Lease Expiry

A lease may expire because a worker stopped, a process paused, or an operation took longer than expected.

Expiry indicates that the ownership claim is no longer valid according to the lease rules.

It does not prove that the previous operation had no external effect.

## 17.3 Lease Renewal

If the implementation supports lease renewal, renewal should follow the defined ownership and timing rules.

A worker should not extend a lease that it no longer owns.

## 17.4 Competing Workers

Concurrent execution introduces race conditions.

Two workers may attempt to acquire the same work.

A worker may finish after another worker has started recovery.

The implementation must enforce its ownership rules at the appropriate boundary.

## 17.5 Leases and Idempotency

A lease can coordinate ownership, but it does not automatically make an external operation idempotent.

The application must still consider what happens if the operation was accepted before a worker lost ownership.

## 17.6 Testing Leases

Tests should cover the lease behaviors implemented by the application, including expiry and recovery paths where applicable.

A passing happy-path lease test is not enough to establish correctness under every concurrent schedule.

---

# 18. Audit Trail and Evidence

Audit information helps explain what the system did.

Evidence helps establish what can be concluded about the result.

These are related concerns, but neither guarantees that every external effect can be reconstructed perfectly.

## 18.1 Why Audit Information Matters

A workflow may involve multiple steps and components.

Without useful records, an operator may be unable to determine where a failure occurred.

Audit information can help connect the original request to the resulting execution attempt.

## 18.2 Useful Audit Fields

Depending on the current data model, useful information may include:

- Workflow identifier.
- Operation identifier.
- Plan metadata.
- Confirmation information.
- Execution attempt identifier.
- Adapter identity.
- Simulation or live mode.
- Start and completion times.
- Lifecycle transitions.
- Result classification.
- Error classification.
- Relevant external identifiers.

The exact fields that are persisted must be verified against the implementation.

## 18.3 Evidence of a Read

A successful live read can establish that the application received data from the external service.

It does not establish that a separate write operation would succeed.

## 18.4 Evidence of a Simulated Operation

A simulation record establishes that the simulation path produced a result.

It does not establish that the external service was changed.

## 18.5 Evidence of a Write

A write operation needs evidence appropriate to that operation.

Depending on the external service, a response may include a resource identifier or a representation of the resulting resource.

A timeout may leave the outcome uncertain.

The application should not infer success solely from the fact that a request was sent.

## 18.6 Audit Data and Privacy

Audit records can contain sensitive operational details.

They should be protected according to the sensitivity of the data they preserve.

They should not be treated as automatically safe to expose to every user or log sink.

---

# 19. Failure Handling

Failures can occur at different layers.

A reliable workflow distinguishes these layers where practical.

## 19.1 Input Failure

The requested operation may be malformed or incomplete.

The application should validate inputs before dispatching work.

## 19.2 Authorization Failure

The operation may not be permitted.

The application should reject it rather than treating a policy failure as a transient execution error.

## 19.3 Configuration Failure

An adapter may be disabled or missing required configuration.

The application should report a controlled failure.

## 19.4 Network Failure

A remote service may be unavailable or unreachable.

The result may be a known failure or an uncertain outcome, depending on when the failure occurred.

## 19.5 Remote API Failure

The external service may reject the request or return an error.

The application should preserve the relevant failure information without exposing secrets.

## 19.6 Persistence Failure

The application may fail to record an execution result.

This can be particularly difficult when an external operation may already have succeeded.

The system should avoid claiming that the external operation did not happen merely because persistence failed.

## 19.7 Process Interruption

The application process may stop during execution.

Recovery should use the recorded workflow state and the available external evidence.

## 19.8 Failure Classification

Failure classifications should be meaningful to the workflow.

A policy denial should not be retried as if it were a temporary network error.

An uncertain remote outcome should not be treated as a confirmed failure.

## 19.9 Error Visibility

The application should provide enough information for an operator to investigate a failure.

Sensitive credentials and private payloads should not be copied into public error messages.

---

# 20. Idempotency and Retries

Idempotency and retry safety are important in distributed workflow execution.

They address different questions.

## 20.1 Idempotency

An operation is idempotent when repeating it under the relevant contract does not create additional effects beyond the intended result.

Not every external API operation is idempotent.

## 20.2 Retry Safety

A retry is safe only when the application can justify repeating the operation under the relevant conditions.

A read operation may be naturally safe to repeat.

A write operation may require an idempotency key, external reconciliation, or explicit operator review.

## 20.3 Timeout Ambiguity

A timeout can happen before or after the remote system accepts a request.

The caller may not know which occurred.

The absence of a successful response is not proof that the remote operation failed.

## 20.4 Retry Policy

A retry policy should consider:

- Operation type.
- Failure classification.
- Whether the request reached the remote service.
- Whether the external API supports idempotency.
- Whether the prior outcome is known.
- Whether the operation requires approval.
- Whether the workflow is still authorized.
- Whether the execution lease remains valid.

## 20.5 Retry Testing

Tests should verify that a retry does not bypass authorization or approval.

They should verify that a known policy denial is not treated as a transient failure.

They should also cover uncertain outcomes where the implementation supports them.

## 20.6 No Universal Guarantee

This README does not claim that all Saffron operations are idempotent.

The retry behavior must be evaluated per operation and adapter.

---

# 21. System Architecture

Saffron separates the web interface, workflow coordination, execution gateway, adapters, and persistence responsibilities.

The diagram below is conceptual.

```text
                      Operator
                         |
                         v
               +--------------------+
               |    Django UI       |
               | Dashboard / Runs   |
               | Plan Confirmation  |
               +---------+----------+
                         |
                         v
               +--------------------+
               | Workflow Layer     |
               | Lifecycle          |
               | Authorization      |
               | Approval Rules     |
               +---------+----------+
                         |
                         v
               +--------------------+
               | Execution Gateway  |
               +---------+----------+
                         |
                +--------+--------+
                |                 |
                v                 v
       +----------------+  +----------------+
       | Simulator      |  | GitHub Adapter |
       |                |  | Read Operations|
       +--------+-------+  +--------+-------+
                |                   |
                +---------+---------+
                          |
                          v
               +--------------------+
               | Outcome Processing |
               | Evidence / Audit   |
               +---------+----------+
                         |
                         v
               +--------------------+
               | Django ORM         |
               | PostgreSQL         |
               +--------------------+
```

This diagram shows logical responsibilities.

It does not establish that every box corresponds to a separate deployable service.

## 21.1 Web Layer

The Django web layer handles incoming HTTP requests and renders the appropriate responses.

It exposes the workflow interface and operational endpoints.

## 21.2 Workflow Layer

The workflow layer coordinates the state and progression of a run.

It applies the rules associated with confirmation and execution.

## 21.3 Execution Gateway

The gateway coordinates the invocation of supported operations.

It provides a boundary between the workflow and adapter implementations.

## 21.4 Adapter Layer

Adapters implement the details of the supported execution mechanisms.

The simulator and GitHub read integration have different operational behavior.

## 21.5 Persistence Layer

The Django ORM provides access to the configured database.

The production database is PostgreSQL hosted by Neon.

## 21.6 Operational Endpoints

The health endpoint checks application responsiveness.

The readiness endpoint checks database connectivity.

These endpoints provide operational signals rather than comprehensive application verification.

---

# 22. Component Responsibilities

The following descriptions identify architectural responsibilities rather than claiming a one-to-one mapping to every module.

## 22.1 Django Settings

The settings module loads environment configuration and defines application behavior.

Production configuration includes the secret key, debug mode, allowed hosts, CSRF trusted origins, database URL, and proxy-related security settings.

## 22.2 URL Configuration

The URL configuration maps HTTP paths to the relevant Django views.

It includes application pages and health-related endpoints.

## 22.3 Health View

The health view returns a small JSON response indicating that the application endpoint is responding.

It does not perform the database query used by readiness.

## 22.4 Readiness View

The readiness view checks the configured database connection by executing a simple query.

If the database check fails, it returns a service-unavailable response.

## 22.5 Workflow Views

The workflow views expose the application interface for the supported run-management operations.

The exact validation and transition behavior is defined by the implementation.

## 22.6 Execution Gateway

The execution gateway coordinates operation dispatch and adapter behavior.

Its exact request and response contracts should be inspected in the source code.

## 22.7 GitHub Adapter

The GitHub adapter implements the configured read operations.

Live behavior is controlled through the feature flag and repository allowlist.

## 22.8 Simulator

The simulator supplies testable execution behavior without claiming that an external operation occurred.

## 22.9 Tests

The test suite validates implemented behavior and helps prevent regressions.

A test passing in isolation does not establish that every hosted integration is configured correctly.

---

# 23. Request and Execution Data Flow

This section describes the conceptual flow of a workflow request.

## 23.1 Step One: Receive the Request

The application receives a request through its web interface.

The request must be valid for the corresponding workflow action.

## 23.2 Step Two: Prepare the Plan

The planning process creates or updates a proposed set of operations.

The plan should remain inspectable before consequential execution.

## 23.3 Step Three: Confirm the Plan

The workflow applies the confirmation rules associated with the request.

The confirmation step should not silently bypass unrelated authorization requirements.

## 23.4 Step Four: Validate Execution Preconditions

The application checks the conditions required for the operation.

These may include configuration, permissions, repository allowlisting, and workflow state.

## 23.5 Step Five: Dispatch the Operation

The gateway coordinates the operation using the configured adapter.

The adapter may be a simulator or a supported live integration.

## 23.6 Step Six: Interpret the Result

The application interprets the adapter result according to the adapter's contract.

It should distinguish successful results, rejected requests, and uncertain outcomes where the implementation supports that distinction.

## 23.7 Step Seven: Record the Outcome

The application records the workflow result according to its persistence model.

The stored information should not imply a stronger external guarantee than the result supports.

## 23.8 Step Eight: Present the Result

The user or operator can inspect the workflow state and available evidence.

The result should be understandable without requiring the operator to assume that every requested action succeeded.

---

# 24. Data Persistence

Saffron uses Django's ORM with PostgreSQL in production.

The database stores the application's persisted workflow data according to its models and migrations.

## 24.1 Database Configuration

The database connection is configured through `DATABASE_URL`.

The settings parse the URL through `dj-database-url`.

The production connection uses PostgreSQL.

## 24.2 Connection Reuse

The application configures database connection reuse and health checks through Django's database configuration.

Connection behavior should be evaluated against the hosting environment and database provider.

## 24.3 Migrations

Django migrations define schema changes.

They should be reviewed and applied as part of a controlled deployment process.

## 24.4 Persistence Failures

A database error can prevent a workflow transition from being saved.

If an external operation has already occurred, the persistence failure may leave an uncertain relationship between the remote outcome and the local record.

This is one reason execution results and recovery logic need careful design.

## 24.5 Database Availability

The readiness endpoint checks whether the application can execute a basic database query.

A successful readiness response confirms connectivity at the time of the check.

It does not prove that every future transaction will succeed.

## 24.6 Data Retention

Data-retention requirements depend on the intended use of the application.

Production operators should establish appropriate retention, backup, and access-control policies for persisted workflow records.

---

# 25. Database Design Considerations

The database is part of the workflow's reliability model.

## 25.1 Schema Evolution

Schema changes should be represented through migrations.

The migration history should remain consistent with the models.

## 25.2 Transaction Boundaries

A database transaction can protect related database operations.

It cannot automatically make an external API call part of the same atomic transaction.

External effects and local database commits require separate coordination.

## 25.3 Concurrency

Concurrent requests can attempt to update the same workflow.

The implementation should use appropriate database constraints, locking, conditional updates, or other concurrency controls where required.

The exact mechanism must be verified in the relevant code path.

## 25.4 Database Backups

Production data should be protected according to the intended recovery requirements.

Backup availability and restoration procedures should be verified independently of application health.

## 25.5 Migration Safety

A successful application build does not prove that the database schema is current.

Migration status should be checked during deployment verification.

## 25.6 Production Isolation

Local tests should not use the shared production database.

The test environment should use an isolated database with controlled data.

---

# 26. Technology Stack

Saffron uses a Python and Django application architecture.

## 26.1 Python

Python provides the application language and the implementation environment for workflow behavior.

## 26.2 Django

Django provides HTTP handling, URL routing, views, configuration, authentication components, and database integration.

The project uses Django 5.2.

## 26.3 Django ORM

The ORM provides model-based access to the configured database.

It also integrates with Django's migration system.

## 26.4 PostgreSQL

PostgreSQL is the production relational database.

The application connects through the configured database URL.

## 26.5 Neon

Neon provides the hosted PostgreSQL database used by the production deployment.

The application must use the correct production connection string and SSL configuration.

## 26.6 Gunicorn

Gunicorn serves the Django WSGI application in production.

The configured start command is:

```bash
gunicorn config.wsgi:application
```

## 26.7 WhiteNoise

WhiteNoise serves collected static assets from the Django deployment.

The build process runs Django's static-file collection command.

## 26.8 pytest

pytest runs the project's automated tests.

## 26.9 pytest-django

pytest-django provides the integration between pytest and Django's testing environment.

## 26.10 dj-database-url

`dj-database-url` parses the database URL into Django's database configuration.

## 26.11 Psycopg

Psycopg provides the PostgreSQL database driver.

## 26.12 Render

Render hosts the web application.

Its environment settings provide the production configuration values.

---

# 27. Repository Structure

The repository contains the Django configuration, workflow application, tests, and deployment files.

```text
saffron/
|
├── config/
|   ├── settings.py
|   ├── urls.py
|   ├── views.py
|   ├── wsgi.py
|   └── asgi.py
|
├── runs/
|   └── workflow application modules and migrations
|
├── tests/
|   └── automated tests
|
├── build.sh
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

This tree is illustrative and not a substitute for the current repository file listing.

## 27.1 `config/settings.py`

Contains Django settings and environment-based configuration.

## 27.2 `config/urls.py`

Defines application URL routing.

## 27.3 `config/views.py`

Contains the health and readiness view functions.

## 27.4 `config/wsgi.py`

Provides the WSGI entry point used by Gunicorn.

## 27.5 `runs/`

Contains the workflow application code and its migrations.

The exact current module structure should be verified against the repository.

## 27.6 `tests/`

Contains automated tests for application behavior.

## 27.7 `build.sh`

Installs dependencies and collects static assets for deployment.

## 27.8 `requirements.txt`

Defines Python dependencies.

## 27.9 `docker-compose.yml`

Defines the local PostgreSQL service used during development.

## 27.10 `.env.example`

Provides an example of the expected environment configuration.

It should contain placeholders rather than real production secrets.

## 27.11 `.gitignore`

Prevents local configuration and other excluded files from being committed.

---

# 28. Configuration and Environment Variables

Saffron uses environment variables for deployment-specific configuration.

Production secrets should be configured through the hosting provider.

They should not be committed to source control.

## 28.1 `DJANGO_SECRET_KEY`

The Django secret key is required.

Use a strong, unique value for production.

Do not reuse a public example secret.

Do not place the production value in this README.

## 28.2 `DJANGO_DEBUG`

Set this variable to:

```text
false
```

for production.

Debug mode should not be enabled on the public deployment.

## 28.3 `DJANGO_ALLOWED_HOSTS`

This variable contains allowed hostnames.

For the current Render deployment, the hostname is:

```text
saffron-lp0q.onrender.com
```

Do not include the URL scheme or a path.

## 28.4 `DJANGO_CSRF_TRUSTED_ORIGINS`

This variable contains trusted origins.

For the current Render deployment, the origin is:

```text
https://saffron-lp0q.onrender.com
```

Unlike `DJANGO_ALLOWED_HOSTS`, the origin includes the HTTPS scheme.

## 28.5 `DATABASE_URL`

This variable contains the database connection URL.

In production, it points to the Neon PostgreSQL database.

Keep the value private because it may contain credentials.

## 28.6 `DATABASE_SSL_REQUIRE`

This setting controls whether the application requires SSL for the database connection.

The intended production value is:

```text
true
```

## 28.7 `DJANGO_USE_X_FORWARDED_PROTO`

This setting controls whether Django trusts the configured proxy HTTPS header.

The intended Render setting is:

```text
true
```

It should be used with the expected hosting proxy configuration.

## 28.8 `SAFFRON_ENABLE_REAL_GITHUB_READS`

This feature flag controls live GitHub read behavior.

The safe initial value is:

```text
false
```

Enable it only after verifying the hosted configuration and allowlist.

## 28.9 `GITHUB_ALLOWED_REPOSITORIES`

This variable contains the repository allowlist.

The currently intended repository is:

```text
harishwaranvijayakumar-code/indexforge
```

## 28.10 `GITHUB_TOKEN`

This variable contains the GitHub credential.

Configure it privately in Render.

Never commit the token or include it in logs.

## 28.11 Environment Configuration Checklist

Before deploying, verify:

- The Django secret key is present.
- Debug mode is disabled.
- The allowed hostname is correct.
- The CSRF trusted origin is correct.
- The database URL points to Neon.
- Database SSL is required.
- Proxy HTTPS handling is configured.
- Live GitHub reads remain disabled until verified.
- The repository allowlist is explicit.
- The GitHub token is private and appropriately scoped.

---

# 29. Local Development

Local development should use an isolated environment.

It should not depend on production credentials or modify production data.

## 29.1 Requirements

Install:

- Python compatible with the project's dependencies.
- Git.
- Docker Desktop if using the included PostgreSQL service.
- A terminal such as PowerShell.

## 29.2 Clone the Repository

```powershell
git clone https://github.com/harishwaranvijayakumar-code/saffron.git
cd saffron
```

## 29.3 Create a Virtual Environment

```powershell
python -m venv .venv
```

## 29.4 Activate the Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

## 29.5 Install Dependencies

```powershell
python -m pip install -r requirements.txt
```

## 29.6 Configure Local Environment Variables

Copy the example configuration:

```powershell
Copy-Item .env.example .env
```

Review the values before running the application.

Use local development credentials.

Do not copy production secrets into a committed file.

## 29.7 Verify the Environment

Run:

```powershell
python manage.py check
```

This checks Django's configuration for reported issues.

It does not prove that every external integration is reachable.

## 29.8 Start the Database

If using the included Docker Compose configuration:

```powershell
docker compose up -d
```

Check the service status:

```powershell
docker compose ps
```

Wait until PostgreSQL reports a healthy state before running migrations or tests.

## 29.9 Apply Migrations

```powershell
python manage.py migrate
```

## 29.10 Start the Development Server

```powershell
python manage.py runserver
```

Open:

[http://127.0.0.1:8000/](http://127.0.0.1:8000/)

## 29.11 Stop the Development Server

Use `Ctrl+C` in the terminal running the server.

## 29.12 Stop Local PostgreSQL

When the database is no longer needed:

```powershell
docker compose down
```

This stops the local services.

It does not remove the persistent database volume unless the corresponding volume-removal option is explicitly used.

---

# 30. Database Setup

Saffron uses PostgreSQL for the production deployment.

The repository also defines a local PostgreSQL development service.

## 30.1 Local Database

The local Docker Compose configuration exposes PostgreSQL on host port `5433`.

The database name and user are configured for local development.

The expected local database URL has this general form:

```text
postgresql://USER:PASSWORD@127.0.0.1:5433/DATABASE
```

Replace the placeholders with the values from the local environment.

## 30.2 Production Database

The production database is hosted by Neon.

The application receives the production URL through `DATABASE_URL`.

## 30.3 Avoid Mixing Environments

Do not point local test runs at the production database.

Tests may create, alter, or delete test data.

A shared production database is not an appropriate default test target.

## 30.4 Verify the Active Database URL

Before running migrations or tests, confirm that the environment points to the intended database.

Do not print a full production URL into a shared log or issue report.

## 30.5 Database Connectivity

The readiness endpoint executes a basic query against the configured database.

A successful response confirms that the database connection worked at the time of the request.

## 30.6 Database Migrations

Migrations should be reviewed and applied deliberately.

The migration state should be verified after deployment.

## 30.7 Connection Errors

If the application cannot connect to PostgreSQL, check:

- The database URL.
- The database hostname.
- The database name.
- The configured username.
- The credential.
- SSL requirements.
- Network availability.
- Provider connection limits.
- Whether the database is available.

Do not expose the connection string while troubleshooting.

---

# 31. Running the Application

The local development server provides the primary entry point for manual testing.

## 31.1 Start the Application

Activate the virtual environment and run:

```powershell
python manage.py runserver
```

## 31.2 Open the Homepage

Navigate to:

```text
http://127.0.0.1:8000/
```

## 31.3 Verify the Health Endpoint

Navigate to:

```text
http://127.0.0.1:8000/health/
```

The expected response is:

```json
{
  "status": "ok",
  "service": "saffron"
}
```

## 31.4 Verify the Readiness Endpoint

Navigate to:

```text
http://127.0.0.1:8000/ready/
```

When the database is available, the expected response is:

```json
{
  "status": "ready",
  "service": "saffron",
  "database": "connected"
}
```

## 31.5 Interpret the Endpoints Correctly

The health endpoint checks application responsiveness.

The readiness endpoint checks database connectivity.

Neither endpoint verifies the entire workflow execution path.

## 31.6 Manual Workflow Verification

Use the application's supported workflow routes to test the intended run-management behavior.

Verify the displayed state after each meaningful operation.

Do not assume that an HTTP response alone proves that an external action occurred.

---

# 32. Testing Strategy

Testing should verify both expected behavior and failure behavior.

The project uses pytest and pytest-django.

## 32.1 Unit Tests

Unit tests should validate focused logic without requiring unnecessary external dependencies.

They are useful for input validation, policy decisions, result handling, and other deterministic behavior.

## 32.2 Django Tests

Django-aware tests can validate HTTP responses, database behavior, and application workflows.

## 32.3 Gateway Tests

Gateway tests should verify the coordination between workflow requests and execution adapters.

They should check both allowed and rejected operations.

## 32.4 Adapter Tests

Adapter tests should validate request construction, response handling, and error behavior.

Live integrations should not be required for every ordinary test.

## 32.5 Persistence Tests

Persistence tests should verify that successful workflow operations are recorded according to the data model.

They should also cover failures that affect persistence.

## 32.6 Authorization Tests

Authorization tests should verify that denied operations do not proceed through the prohibited execution path.

## 32.7 Feature-Flag Tests

Tests should confirm that the live GitHub integration remains disabled when the feature flag is false.

They should also verify the intended behavior when the flag is explicitly enabled in a controlled integration test.

## 32.8 Readiness Tests

Readiness tests should cover a healthy database and a simulated database failure.

## 32.9 Regression Tests

Regression tests should protect previously corrected behavior.

They are particularly important when modifying the gateway, adapter, or configuration layers.

## 32.10 Test Isolation

Ordinary tests should use an isolated test database.

Live external reads should be disabled unless a test intentionally exercises the live integration.

## 32.11 Test Results

A test suite passing confirms the tested behavior under the conditions of that run.

It does not guarantee correctness under every external service condition or production workload.

---

# 33. Verification Commands

Run these commands from the repository root with the virtual environment activated.

## 33.1 Django System Check

```powershell
python manage.py check
```

This checks the Django application configuration.

## 33.2 Full Test Suite

```powershell
python -m pytest -q
```

This runs the project tests.

## 33.3 Dependency Consistency

```powershell
python -m pip check
```

This checks installed dependency requirements.

## 33.4 Migration Consistency

```powershell
python manage.py makemigrations --check --dry-run
```

This checks whether model changes would produce new migrations.

## 33.5 Planned Migrations

```powershell
python manage.py migrate --plan
```

This shows migrations Django plans to apply.

## 33.6 Static-File Collection

```powershell
python manage.py collectstatic --noinput
```

This collects static files for the configured deployment storage.

## 33.7 Deployment Settings Check

```powershell
python manage.py check --deploy
```

This runs Django's deployment-oriented checks.

Review warnings in the context of the actual production configuration.

## 33.8 Git Whitespace Check

```powershell
git diff --check
```

This checks the current diff for whitespace problems.

## 33.9 Git Status

```powershell
git status --short --branch
```

This shows the current working-tree and branch status.

## 33.10 Review Before Committing

```powershell
git diff
```

Review the changes before staging and committing them.

---

# 34. Production Deployment

Saffron is deployed as a Django web service on Render.

Neon PostgreSQL provides the production database.

## 34.1 Deployment Components

```text
GitHub Repository
        |
        v
Render Build
        |
        v
Dependency Installation
        |
        v
Static-File Collection
        |
        v
Gunicorn Startup
        |
        v
Django Application
        |
        v
Neon PostgreSQL
```

## 34.2 Live Application

The application URL is:

[https://saffron-lp0q.onrender.com](https://saffron-lp0q.onrender.com)

## 34.3 Build Command

The configured Render build command is:

```bash
bash build.sh
```

## 34.4 Build Script

The repository's build script installs dependencies and collects static files.

Its purpose is to prepare the application package for deployment.

Database migrations are handled as a separate controlled step.

## 34.5 Start Command

The configured start command is:

```bash
gunicorn config.wsgi:application
```

## 34.6 Production Settings

Production configuration should use:

- A unique Django secret key.
- Debug mode disabled.
- The correct allowed hostname.
- The correct CSRF trusted origin.
- The Neon database URL.
- Database SSL requirements.
- Correct proxy HTTPS handling.
- Explicit integration configuration.

## 34.7 Deployment Validation

After deployment, verify that the application starts.

Check the health endpoint.

Check database readiness.

Inspect the main workflow pages.

Test a safe workflow.

Inspect the persisted outcome.

Verify the configured integration mode.

## 34.8 Build Success Is Not Enough

A successful build confirms that the build process completed.

It does not establish that the database is reachable.

It does not establish that migrations are current.

It does not establish that every workflow route works.

It does not establish that live GitHub integration is correctly configured.

Each of these requires separate verification.

---

# 35. Render Configuration

Render hosts the Django application.

The service configuration must match the application's settings.

## 35.1 Repository

The repository is:

[harishwaranvijayakumar-code/saffron](https://github.com/harishwaranvijayakumar-code/saffron)

## 35.2 Branch

The intended deployment branch is:

```text
main
```

## 35.3 Runtime

Use the Python runtime supported by the project dependencies.

The hosted environment must be able to install the pinned requirements.

## 35.4 Build Command

```bash
bash build.sh
```

## 35.5 Start Command

```bash
gunicorn config.wsgi:application
```

## 35.6 Health Check Path

Configure:

```text
/health/
```

The health check should return HTTP 200 when the application is responding.

## 35.7 Hostname

The current hostname is:

```text
saffron-lp0q.onrender.com
```

Configure `DJANGO_ALLOWED_HOSTS` with the hostname without a URL scheme.

## 35.8 CSRF Origin

Configure the corresponding origin as:

```text
https://saffron-lp0q.onrender.com
```

## 35.9 Environment Variables

Set production environment variables through Render's environment settings.

Do not place credentials in the source repository.

## 35.10 Runtime Logs

Inspect Render logs when the application fails to start or returns unexpected errors.

Distinguish build failures from runtime failures.

## 35.11 Health Check Failures

A Django HTTP 400 response may indicate an invalid or unrecognized host header.

A database-related readiness failure indicates that the application could not complete its database check.

Use the specific error to identify the failing boundary.

---

# 36. Neon PostgreSQL Configuration

Neon provides the production PostgreSQL database.

Saffron connects to it through `DATABASE_URL`.

## 36.1 Connection String

Configure the connection string privately through the hosting provider.

Do not commit the URL to Git.

## 36.2 SSL

The production configuration requires SSL for the database connection.

Verify that the URL and settings are compatible with the selected Neon connection method.

## 36.3 Connectivity

The readiness endpoint checks database connectivity.

A successful response is evidence that the application can reach the database at the time of the check.

## 36.4 Migrations

Ensure that the production database has the migrations required by the deployed code.

Do not assume that a successful application build has applied database migrations.

## 36.5 Local and Production Separation

Local development and tests should use the local database.

Production operations should use the configured Neon database.

Avoid accidentally pointing tests at the shared production database.

## 36.6 Connection Limits

Database providers impose connection constraints.

Application worker counts and connection reuse should be considered when configuring production.

## 36.7 Recovery

Production operators should understand the available database backup and recovery options.

Recovery procedures should be tested according to the intended service requirements.

---

# 37. Health and Readiness Checks

Saffron exposes two operational endpoints.

They answer different questions.

## 37.1 Health Endpoint

Path:

```text
/health/
```

Expected response:

```json
{
  "status": "ok",
  "service": "saffron"
}
```

The endpoint indicates that the application is responding to the request.

## 37.2 Readiness Endpoint

Path:

```text
/ready/
```

Expected successful response:

```json
{
  "status": "ready",
  "service": "saffron",
  "database": "connected"
}
```

The endpoint checks the configured database by executing a simple query.

## 37.3 Database Failure

If the readiness query fails, the endpoint returns HTTP 503.

The response indicates that the service is not ready according to the database check.

## 37.4 Why Both Endpoints Exist

A process may be running while the database is unavailable.

A health check can succeed even when database readiness fails.

Separate endpoints allow deployment tooling and operators to distinguish those conditions.

## 37.5 What the Endpoints Do Not Prove

The endpoints do not prove that:

- Every workflow route works.
- All migrations are current.
- GitHub credentials are valid.
- Every adapter is available.
- A workflow can complete successfully.
- External writes are enabled.
- Recovery works under every failure mode.

These properties require separate verification.

## 37.6 Current Hosted Verification

The hosted endpoints were opened successfully and returned the expected responses:

- `/health/` returned `status: ok`.
- `/ready/` returned `status: ready` and `database: connected`.

This confirms the observed application response and database connectivity at that time.

---

# 38. Database Migrations

Django migrations manage database schema changes.

They should be treated as deployment operations rather than incidental side effects of application startup.

## 38.1 Local Migration Check

Run:

```powershell
python manage.py migrate --plan
```

This shows the migration operations Django plans to apply.

## 38.2 Migration Consistency

Run:

```powershell
python manage.py makemigrations --check --dry-run
```

This checks whether model changes require new migration files.

## 38.3 Controlled Production Migration

Before applying production migrations:

1. Confirm the target database.
2. Confirm the deployed code version.
3. Review the migration plan.
4. Ensure the operation is authorized.
5. Apply the migrations through the chosen deployment procedure.
6. Verify the resulting migration state.
7. Check database readiness.
8. Test the affected workflow paths.

## 38.4 Migration Failure

A migration may fail because of a schema conflict, database permission issue, connection failure, or invalid migration operation.

Investigate the specific error before retrying.

## 38.5 Migration and Application Compatibility

A schema change may affect application code.

Deployment sequencing should account for compatibility between the running application and the database schema.

## 38.6 Migration Verification

A successful migration command is useful evidence.

The application should also be checked against the migrated database afterward.

---

# 39. GitHub Credentials and Repository Allowlisting

The GitHub integration depends on configuration and credential permissions.

## 39.1 Credential Storage

Store `GITHUB_TOKEN` in Render's private environment configuration.

Never place the token in the README.

Never commit it to Git.

Never include it in public diagnostic output.

## 39.2 Repository Allowlist

The current intended allowlist entry is:

```text
harishwaranvijayakumar-code/indexforge
```

Use the repository identifier in the format expected by the application.

## 39.3 Live Read Feature Flag

The environment variable is:

```text
SAFFRON_ENABLE_REAL_GITHUB_READS
```

The safe initial value is:

```text
false
```

## 39.4 Least Privilege

Use the minimum credential permissions required for the supported read operations.

Do not grant broad write access merely to enable read-only workflow inspection.

## 39.5 Integration Verification

Verify the following before enabling live reads:

- The credential is configured.
- The repository allowlist is correct.
- The application can reach GitHub.
- The selected operation is read-only.
- The response is identified as a live result.
- Errors are handled correctly.
- The normal test suite remains isolated from live external effects.

## 39.6 Writes Remain Separate

A successful live read does not enable or validate an external write.

Issue-comment creation remains simulated and approval-gated in the current configuration.

---

# 40. Security Model

Saffron interacts with workflow state and may connect to external systems.

Security depends on correct configuration, access control, credential handling, and execution policy.

## 40.1 Secret Management

Production secrets belong in the hosting provider's secret configuration.

They should not be committed to Git.

## 40.2 Django Debug Mode

Debug mode should be disabled in production.

## 40.3 Host Validation

Configure allowed hosts to match the actual service hostname.

Do not disable host validation merely to suppress HTTP 400 errors.

## 40.4 CSRF Protection

Configure the trusted origin to match the actual HTTPS origin.

Do not add unrelated origins without a clear reason.

## 40.5 Database Security

Protect the production database URL.

Use the intended SSL configuration.

Restrict access according to the deployment's requirements.

## 40.6 GitHub Credential Scope

Use a credential with only the required permissions.

Do not assume that a repository allowlist limits all actions the credential itself can perform.

## 40.7 Authorization

The application should enforce authorization at the relevant operation boundary.

A generated plan must not bypass authorization.

## 40.8 Approval

Keep approval requirements for consequential operations.

Do not treat a generic confirmation as permission for every future action.

## 40.9 Audit Data

Audit information can contain sensitive details.

Restrict access to records according to their sensitivity.

## 40.10 External Dependencies

Treat external API responses as untrusted input.

Validate response structure before using it in subsequent workflow operations.

## 40.11 Error Messages

Error responses should be useful without exposing credentials or other sensitive values.

## 40.12 Deployment Security

Review the actual production settings and environment configuration.

A deployment should not be considered secure merely because the homepage is accessible over HTTPS.

---

# 41. Data Privacy

Workflow systems can handle operational information that should not be exposed unnecessarily.

## 41.1 Potentially Sensitive Data

Workflow records may include operation details, repository identifiers, execution results, error messages, or external resource references.

## 41.2 Credential Protection

Credentials must not be copied into logs, README files, or issue reports.

## 41.3 Data Minimization

Store the information needed for workflow operation, auditing, and recovery.

Avoid preserving unrelated sensitive information without a clear requirement.

## 41.4 Database Access

Restrict access to the production database.

Use appropriate provider access controls.

## 41.5 Log Access

Application logs should be treated as potentially sensitive operational records.

## 41.6 External Requests

Only send data to an external service when the operation and its authorization permit it.

## 41.7 Simulation

Simulation can reduce the need to contact external systems during testing.

It does not automatically make all test data safe to publish.

## 41.8 Retention

Establish retention rules appropriate to the application and its intended users.

## 41.9 Public Deployment

Do not assume that a public application URL means every workflow record should be publicly accessible.

Access control should match the sensitivity of the data and the application's intended use.

---

# 42. Operational Observability

Operational observability helps distinguish a running application from a functioning workflow system.

## 42.1 Application Logs

Logs can help identify startup failures, request errors, and integration problems.

They should not expose secrets.

## 42.2 Health Monitoring

The health endpoint provides a basic application-response signal.

## 42.3 Readiness Monitoring

The readiness endpoint provides a basic database-connectivity signal.

## 42.4 Workflow Outcomes

Operators need to inspect workflow results and execution errors through the application's supported interface and records.

## 42.5 Adapter Failures

Adapter failures should be distinguishable from validation and authorization failures where the implementation supports that distinction.

## 42.6 Deployment Logs

Render's build and runtime logs help identify different categories of failure.

A dependency installation failure differs from a Gunicorn startup failure.

A host-validation error differs from a database connection error.

## 42.7 Integration Observability

Live integration behavior should be verified through operation-specific results and logs.

A healthy web endpoint does not prove that GitHub is reachable.

## 42.8 Monitoring Limitations

Health and readiness endpoints do not replace structured application monitoring, alerting, performance metrics, or incident investigation.

---

# 43. Reliability Invariants

Reliability expectations should be expressed as properties that can be checked.

## 43.1 Authorization Invariant

A prohibited operation must not execute through the protected path.

## 43.2 Confirmation Invariant

A proposed plan must not be treated as confirmed unless the required confirmation step has occurred.

## 43.3 Adapter Invariant

An operation must use an adapter that supports the requested behavior.

## 43.4 Simulation Invariant

A simulated result must not be presented as proof of a real external side effect.

## 43.5 Allowlist Invariant

A live GitHub read must respect the configured repository allowlist.

## 43.6 Configuration Invariant

Disabled live-read configuration must not silently become enabled.

## 43.7 Persistence Invariant

A recorded result should correspond to the outcome the application actually observed.

## 43.8 Failure Invariant

A known failure must not be represented as a successful operation.

## 43.9 Recovery Invariant

Recovery must not silently bypass the applicable authorization and approval rules.

## 43.10 Lease Invariant

Expired ownership must not be treated as proof that no external side effect occurred.

## 43.11 Secret Invariant

Credentials must not be committed to source control or intentionally exposed through public responses.

## 43.12 Database Invariant

A successful readiness response must correspond to a successful database check at the time of the request.

## 43.13 Test Isolation Invariant

Ordinary tests must not unintentionally perform live external operations or modify production data.

## 43.14 Evidence Invariant

The application should not claim a stronger outcome than its available evidence supports.

---

# 44. Testing Live Integrations Safely

Live integration tests differ from ordinary unit tests.

They may depend on network availability, external credentials, remote permissions, and third-party service behavior.

## 44.1 Default Test Mode

Keep:

```text
SAFFRON_ENABLE_REAL_GITHUB_READS=false
```

for the ordinary test suite unless a test explicitly requires live behavior.

## 44.2 Local Database

Use the local development database or a dedicated test database.

Do not use the shared production database as the default test database.

## 44.3 Test Scope

Choose a narrowly scoped, non-destructive operation.

For GitHub integration, workflow-run reads are preferable to write operations when verifying basic connectivity.

## 44.4 Repository Scope

Use only the intended allowlisted repository.

Do not broaden the allowlist just to make a failing test pass.

## 44.5 Credential Scope

Use an appropriately scoped credential.

Do not expose the token while debugging.

## 44.6 Test Interpretation

A live read that succeeds establishes that the tested read path worked under the tested configuration.

It does not establish that all GitHub operations work.

It does not establish that a write operation is safe.

It does not establish that every deployment environment has the same configuration.

## 44.7 Return to Safe Defaults

After a controlled live integration test, restore the ordinary test configuration.

Verify that the normal suite still passes with live reads disabled.

---

# 45. Troubleshooting

This section lists common failure categories and the first checks to perform.

## 45.1 Application Does Not Start

Check the Render runtime logs.

Verify that dependencies installed successfully.

Verify that the Gunicorn start command is correct.

Verify that required environment variables exist.

Do not include secret values in a shared error report.

## 45.2 Build Fails

Check the first meaningful error in the build log.

Determine whether the problem concerns dependency installation, static-file collection, or configuration.

A pip update notice alone is not evidence of a build failure.

## 45.3 HTTP 400 Response

Check the hostname in `DJANGO_ALLOWED_HOSTS`.

Check the actual hostname used by the request.

Inspect the runtime logs for `Invalid HTTP_HOST header`.

Do not disable host validation as a general workaround.

## 45.4 CSRF Failure

Check the configured CSRF trusted origin.

Ensure it matches the actual origin, including the HTTPS scheme.

Review the request's origin and the deployment's proxy configuration.

## 45.5 Health Check Fails

Open `/health/` directly.

Check whether the endpoint returns HTTP 200.

Inspect the runtime logs for the associated request.

## 45.6 Readiness Check Fails

Open `/ready/`.

If the endpoint returns HTTP 503, inspect the database configuration and runtime logs.

Check the Neon URL, credentials, SSL configuration, and database availability.

## 45.7 Database Connection Failure

Verify that `DATABASE_URL` points to the intended database.

Check the database host and database name.

Check SSL requirements.

Check whether the database provider is reachable.

Do not print the full connection string into logs.

## 45.8 Missing Database Tables

Check migration status.

Review the migration plan.

Apply the required migrations through the controlled deployment procedure.

Verify readiness afterward.

## 45.9 Static Assets Missing

Check that `collectstatic` completed successfully during the build.

Verify the configured static-file storage.

Inspect the browser network panel for failed static-file requests.

## 45.10 GitHub Read Fails

Check whether live reads are enabled.

Verify the repository allowlist.

Verify the credential's permissions.

Check network and remote API errors.

Do not assume the problem is fixed by broadening the credential's permissions without understanding the failure.

## 45.11 GitHub Operation Is Simulated

Check the live-read feature flag and the operation being invoked.

Confirm that the operation belongs to the implemented live-read capability.

Do not assume a read-only integration enables live writes.

## 45.12 Tests Fail After Enabling Live Reads

Restore:

```powershell
$env:SAFFRON_ENABLE_REAL_GITHUB_READS = "false"
```

Run the tests against the local test database.

Investigate whether test fixtures are being sent to the live adapter.

Do not change the production repository allowlist merely to accommodate unrelated unit-test fixtures.

## 45.13 Unexpected Test Database

Check the active `DATABASE_URL`.

Confirm that it points to the local or dedicated test environment.

Do not run destructive test operations against Neon production.

## 45.14 Migration Check Reports Changes

Inspect the model changes.

Determine whether a migration file is required.

Generate and review the migration before deploying.

## 45.15 Workflow Result Is Unclear

Inspect the workflow record and execution result.

Determine whether the operation ran in simulation or live mode.

Distinguish a recorded request from a confirmed external outcome.

## 45.16 Recovery Does Not Behave as Expected

Inspect the lifecycle state and lease state.

Determine whether an earlier execution may have produced an external side effect.

Avoid retrying uncertain writes blindly.

## 45.17 General Diagnostic Rule

Identify the failing boundary before changing configuration.

A problem in host validation should not be treated as a database problem.

A database connectivity problem should not be treated as a GitHub authorization problem.

A simulated operation should not be treated as a failed live write.

---

# 46. Known Limitations

The current system has boundaries that should remain explicit.

## 46.1 Integration Scope

Only the operations implemented by the configured adapters should be treated as supported.

## 46.2 GitHub Read Scope

The GitHub integration supports configured read operations.

It should not be described as unrestricted repository automation.

## 46.3 Write Scope

Issue-comment creation remains simulated and approval-gated in the current configuration.

## 46.4 AI Planning

AI-assisted planning does not guarantee that a plan is correct, complete, or authorized.

## 46.5 External Failures

The application cannot guarantee that an external service will always be available.

## 46.6 Rollback

Not every external side effect can be reversed.

## 46.7 Uncertain Outcomes

A timeout may leave the outcome of an external operation uncertain.

## 46.8 Database Availability

The readiness endpoint checks database connectivity at a point in time.

It does not guarantee uninterrupted availability.

## 46.9 Production Scale

The available verification evidence does not establish suitability for every workload or scale.

## 46.10 Security

Correct configuration and implementation reduce risk but do not eliminate every security risk.

## 46.11 Test Coverage

Passing tests validate tested behavior under the tested conditions.

They do not prove that all possible execution schedules and external failures have been covered.

## 46.12 Observability

Health and readiness endpoints provide basic signals.

They are not a complete monitoring or incident-management system.

---

# 47. Engineering Roadmap

The roadmap identifies areas for continued investigation and engineering.

These are potential improvements rather than claims that all work has been completed.

## 47.1 Authorization Regression Coverage

Expand tests around permitted and prohibited operations.

Verify that rejected operations cannot bypass the intended gateway.

## 47.2 Plan Revision Semantics

Review how changes to a plan interact with confirmation.

Ensure that the implemented behavior is explicit and testable.

## 47.3 Execution Lifecycle Coverage

Expand tests for interrupted execution and recovery.

Verify the transitions that the current data model supports.

## 47.4 Lease Concurrency

Test competing workers and lease expiry where applicable.

Verify that stale ownership does not silently authorize a second execution.

## 47.5 Retry Safety

Document retry behavior per operation.

Test idempotency and uncertain outcomes where supported.

## 47.6 Audit Completeness

Review whether the persisted records contain enough information to investigate important execution outcomes.

Avoid storing unnecessary sensitive data.

## 47.7 GitHub Integration Coverage

Expand tests for repository allowlisting, credential errors, remote failures, and feature-flag behavior.

## 47.8 Operational Logging

Improve the ability to identify failures by workflow, execution attempt, and adapter.

Avoid exposing secrets or private payloads.

## 47.9 Database Recovery

Review backup, restoration, and recovery procedures for the production database.

## 47.10 Deployment Verification

Automate the checks that can safely be run after deployment.

Keep production migration operations controlled.

## 47.11 Additional Adapters

Add new adapters only when their authorization, configuration, error, and evidence requirements are defined.

## 47.12 Documentation Maintenance

Keep this README aligned with the implementation.

Update documented capabilities only after the corresponding code and verification evidence exist.

---

# 48. Project Verification Record

This section records known verification facts without claiming more than they establish.

## 48.1 Automated Tests

The recorded local test suite completed with:

```text
136 passed
```

The test run used live GitHub reads disabled.

This result applies to that local verification session.

## 48.2 Django System Check

The application has previously passed the Django system check in the local development environment.

## 48.3 Production Deployment

The Render build completed successfully.

Gunicorn started and the application was marked live by Render.

## 48.4 Health Endpoint

The hosted health endpoint returned:

```json
{
  "status": "ok",
  "service": "saffron"
}
```

## 48.5 Database Readiness

The hosted readiness endpoint returned:

```json
{
  "status": "ready",
  "service": "saffron",
  "database": "connected"
}
```

## 48.6 Database Connectivity

The readiness response confirms that the deployed application could execute its database check at the time of verification.

## 48.7 Live GitHub Read

A prior controlled integration test successfully retrieved workflow-run information from the intended GitHub repository.

That test establishes the behavior of the specific read path under that configuration.

It does not establish that all integrations or write operations are enabled.

## 48.8 Remaining Verification

The following should be tested independently before treating the entire system as production-ready:

- Main workflow creation.
- Plan confirmation.
- Authorization boundaries.
- Persistence of workflow results.
- Lifecycle transitions.
- Recovery behavior.
- Adapter failure handling.
- GitHub allowlist enforcement.
- Production migration status.
- Credential scope.
- External integration behavior under failure.

## 48.9 Verification Principle

A verification record should distinguish observed facts from assumptions.

A passing test is evidence for the behavior it exercises.

A healthy endpoint is evidence for the check it performs.

A successful read is evidence for the tested read operation.

None of these should be expanded into a guarantee about untested behavior.

---

# 49. Engineering Methodology

Saffron follows an evidence-oriented development process.

## 49.1 Inspect Before Changing

Review the current implementation, configuration, tests, and relevant project constraints before proposing a change.

## 49.2 Define the Behavior

Specify what the operation should do.

Identify its authorization requirements.

Identify its expected failure behavior.

## 49.3 Preserve Boundaries

Keep planning, confirmation, authorization, execution, and evidence distinct.

## 49.4 Implement the Smallest Correct Change

Avoid changing unrelated behavior when addressing a specific defect.

## 49.5 Test the Intended Behavior

Write tests that validate the expected result and the important rejection paths.

## 49.6 Test Regression Risk

Run the relevant focused tests.

Run the full test suite when the change affects shared infrastructure or execution behavior.

## 49.7 Verify Configuration

Check the active environment variables and database target.

Do not assume the local environment matches production.

## 49.8 Review the Diff

Inspect the staged changes before committing.

Confirm that secrets and local-only files are not included.

## 49.9 Deploy Deliberately

Use the intended build and start commands.

Handle database migrations as a controlled deployment step.

## 49.10 Verify the Hosted Result

Check health, readiness, and the affected workflow path.

Inspect logs when an expected behavior does not occur.

## 49.11 Record Evidence

Document what was tested and what remains unverified.

## 49.12 Avoid Unsupported Claims

Do not document a planned feature as completed.

Do not describe simulated behavior as a live external action.

Do not treat a successful deployment as proof that every capability works.

---

# 50. Final Project Thesis

Saffron is built around one practical distinction:

**An assistant can help decide what to do. The application must still govern what is allowed to happen.**

A useful workflow platform needs more than an intelligent plan.

It needs explicit confirmation.

It needs authorization boundaries.

It needs controlled execution.

It needs deliberate failure handling.

It needs lifecycle state and recovery behavior.

It needs evidence that distinguishes simulated output from external effects.

It needs tests that cover both success and failure.

It needs deployment checks that measure the actual boundaries of the system.

Saffron brings these concerns into a single workflow architecture.

The objective is not automation at any cost.

The objective is automation that can be inspected, constrained, tested, and improved.

**Saffron — make the plan explicit, make execution accountable, and leave evidence behind.**