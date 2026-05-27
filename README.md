# PAS Invoice Reconciliation App

A first usable local prototype for matching plant hire invoices against the Plant tab.

## How to run

1. Install Python 3.10+
2. Open this folder in Command Prompt / PowerShell
3. Run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app will open in your browser.

## What it does

- Upload latest Material & Plant Orders workbook
- Upload invoice PDFs or ZIP files
- Extract invoice records, including multi-invoice PDFs
- Match at invoice level
- Produce Matched / Unmatched tabs
- Show match percentage
- Export Excel reconciliation workbook

## Prototype notes

This is a working first version. Supplier-specific parsing rules will improve over time as more invoices are tested.
