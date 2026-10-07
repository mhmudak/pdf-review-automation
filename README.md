# PDF Review Automation

Automated workflow for extracting native PDF review annotations, mapping them to the correct publication pages, deduplicating reviewer feedback, and synchronizing results with Google Sheets.

> **Status:** In active development.

## Problem

Editorial and content-review teams often receive multiple annotated PDF files from different reviewers.

Manually consolidating those comments creates several problems:

- reviewers may work on full or partial PDFs
- PDF page numbers may differ from printed book pages
- the same file may be renamed or uploaded again
- revised PDFs may contain old, modified, and new comments
- reviewer names may appear differently across PDF metadata
- manual copy/paste into spreadsheets is slow and error-prone

This project automates that workflow.

## Target Workflow

```text
Google Drive
    ↓
Scheduled Cloud Run job
    ↓
Python + PyMuPDF
    ↓
Native PDF annotation extraction
    ↓
Reviewer normalization
    ↓
Publication page mapping
    ↓
Deduplication / idempotent processing
    ↓
Google Sheets
    ↓
Processing notification
```

## Core Features

- Extract native PDF annotations without OCR
- Support full and partial PDFs
- Identify reviewers dynamically
- Preserve original reviewer comments
- Map PDF pages to publication/book pages
- Detect exact duplicate files using SHA-256
- Deduplicate annotations using stable annotation identity
- Update changed annotations instead of creating duplicates
- Keep an auditable processing history
- Automatically create reviewer-specific outputs
- Flag uncertain reviewer or page mappings for manual review
- Designed for scheduled serverless execution with Google Cloud Run

## Engineering Principles

### Idempotency

Processing the same unchanged document multiple times should produce the same logical dataset without duplicate annotations.

### Source Preservation

Original PDF annotations are treated as evidence and are not silently rewritten.

### Reviewer Safety

Reviewer tabs are created only when a verified full reviewer name can be determined.

Technical usernames or ambiguous identities are routed for manual review.

### Page Mapping

The system does not assume that:

```text
PDF page = publication page
```

Partial documents can be aligned against a reference publication using page-content fingerprints.

### Privacy

Production data is intentionally excluded from this repository.

The repository does not contain:

- real reviewer PDFs
- production reviewer comments
- private email addresses
- Google Drive file IDs
- Google Sheets IDs
- service-account credentials
- production environment variables

Configuration is supplied through environment variables.

## Tech Stack

- Python
- PyMuPDF
- Google Drive API
- Google Sheets API
- Google Cloud Run
- Google Cloud Scheduler
- Google Service Accounts
- Docker
- Git / GitHub

## Project Structure

```text
pdf-review-automation/
├── src/
├── tests/
├── docs/
├── sample-data/
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Current Development Milestone

The extraction and data-model workflow is being validated against annotated PDF test documents before deployment to Google Cloud.

The production target is a fully automated workflow where placing a reviewed PDF into a configured Google Drive folder is sufficient to trigger processing during the next scheduled execution.

## Planned Deployment

```text
Shared Google Drive Folder
        ↓
Google Cloud Scheduler
        ↓
Cloud Run
        ↓
PDF Processing Pipeline
        ↓
Google Sheets Backend
        ↓
Reviewer Views
        ↓
Email Processing Summary
```

## Future Work

- Production Cloud Run deployment
- Scheduled Drive-folder scanning
- Automated email processing reports
- Expanded automated tests
- Sanitized public demo
- Architecture documentation

## Author

Built as a workflow-automation engineering project focused on replacing repetitive editorial operations with reliable, auditable automation.