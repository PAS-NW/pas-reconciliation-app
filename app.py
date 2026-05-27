import io
import re
import zipfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    from pypdf import PdfReader
except Exception:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        PdfReader = None

PAS_YELLOW = "#FFD400"
PAS_BLACK = "#0A0A0A"
PAS_DARK = "#171717"
PAS_GREY = "#F4F4F4"

st.set_page_config(page_title="PAS Invoice Reconciliation", layout="wide")

st.markdown(
    f"""
    <style>
    .stApp {{ background: #f5f5f5; }}
    section[data-testid="stSidebar"] {{ background: {PAS_BLACK}; color: white; }}
    section[data-testid="stSidebar"] * {{ color: white; }}
    .block-container {{ padding-top: 1.4rem; padding-bottom: 2rem; }}
    .pas-hero {{
        background: linear-gradient(135deg, {PAS_BLACK} 0%, #202020 74%, {PAS_YELLOW} 135%);
        border-radius: 22px;
        padding: 26px 28px;
        margin-bottom: 20px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.12);
    }}
    .pas-title {{ color: white; font-size: 34px; font-weight: 900; margin: 0; letter-spacing: -0.03em; }}
    .pas-subtitle {{ color: {PAS_YELLOW}; font-size: 15px; margin-top: 4px; }}
    .kpi-card {{
        background: white;
        border-radius: 18px;
        padding: 18px 20px;
        border: 1px solid #e8e8e8;
        box-shadow: 0 3px 12px rgba(0,0,0,0.04);
        min-height: 118px;
    }}
    .kpi-label {{ color: #333; font-size: 14px; font-weight: 700; margin-bottom: 8px; }}
    .kpi-value {{ color: {PAS_YELLOW}; font-size: 36px; font-weight: 900; line-height: 1.05; text-shadow: 0 1px 0 #111; }}
    .kpi-sub {{ color: #555; font-size: 13px; margin-top: 6px; }}
    .section-card {{ background: white; border-radius: 18px; padding: 20px; border: 1px solid #e9e9e9; }}
    .stButton > button, .stDownloadButton > button {{
        background: {PAS_YELLOW} !important;
        color: {PAS_BLACK} !important;
        border: 1px solid {PAS_BLACK} !important;
        border-radius: 12px !important;
        font-weight: 900 !important;
    }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px; }}
    .stTabs [data-baseweb="tab"] {{
        background: white;
        border-radius: 12px 12px 0 0;
        color: {PAS_BLACK};
        font-weight: 800;
        border: 1px solid #ddd;
    }}
    .stTabs [aria-selected="true"] {{ background: {PAS_YELLOW} !important; color: {PAS_BLACK} !important; }}
    div[data-testid="stDataFrame"] div[role="columnheader"] {{
        background: {PAS_YELLOW} !important;
        color: {PAS_BLACK} !important;
        font-weight: 900 !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.image("pas_logo.png", use_column_width=True)
    st.markdown("### PAS Reconciliation")
    st.markdown("Upload the Plant workbook and invoice PDFs/ZIP, then export a clean reconciliation workbook.")
    st.markdown("---")
    st.markdown("**Current rules**")
    st.markdown("- Invoice-level approval")
    st.markdown("- Full order reference required")
    st.markdown("- Global rate/value extraction")
    st.markdown("- Movement only from actual charge lines")
    st.markdown("- Multi-page invoices stay together")

st.markdown(
    """
    <div class="pas-hero">
      <div class="pas-title">PAS Invoice Reconciliation</div>
      <div class="pas-subtitle">PAS NW Ltd · v5 structured extraction · invoice-level approval</div>
    </div>
    """,
    unsafe_allow_html=True,
)

BAD_SUPPLIER_PATTERNS = [
    "invoice", "invoice no", "invoice number", "vat", "vat number", "account", "account no",
    "customer", "customer ref", "your ref", "order no", "page", "date", "due date",
    "delivery address", "site address", "ship to", "bill to", "hire period", "total charge",
    "weekly rate", "payment", "bank", "sort code", "goods total", "invoice total", "net total",
]

MOVEMENT_TERMS = ["delivery", "collection", "haulage", "transport", "low loader", "lowloader", "uplift", "cartage", "movement", "carriage"]
ADDRESS_TERMS = ["delivery address", "delivery site", "site address", "ship to", "delivery details", "delivery contact", "collection address"]

STATUS_WORDS = ["on hire", "off-hired", "off hired", "purchase", "repair", "maintenance", "damage", "charges", "movement", "operated plant"]


def clean_cell(value) -> str:
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.lower() in ["nan", "none", "nat"]:
        return ""
    return value


def norm(value) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_cell(value).upper())


def money_to_float(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"-?£?\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.([0-9]{2}))?", text)
    if not match:
        return None
    whole = match.group(1).replace(",", "")
    dec = match.group(2) or "00"
    try:
        return float(f"{whole}.{dec}")
    except Exception:
        return None


def find_col(columns: List[str], keywords: List[str]) -> Optional[str]:
    norm_cols = {c: re.sub(r"[^a-z0-9]+", "", str(c).lower()) for c in columns}
    for key in keywords:
        nkey = re.sub(r"[^a-z0-9]+", "", key.lower())
        for col, ncol in norm_cols.items():
            if nkey == ncol:
                return col
    for key in keywords:
        nkey = re.sub(r"[^a-z0-9]+", "", key.lower())
        for col, ncol in norm_cols.items():
            if nkey in ncol:
                return col
    return None


def build_order_ref(job: str, order: str) -> str:
    job = clean_cell(job).upper().replace(" ", "")
    order = clean_cell(order).upper().replace(" ", "")
    if not job and not order:
        return ""
    if "/" in order and not job:
        return order
    if "/" in job and not order:
        return job
    if job and order:
        if order.startswith(job):
            return order
        return f"{job}/{order}"
    return job or order


def load_plant_workbook(uploaded_file) -> Tuple[pd.DataFrame, Dict[str, str]]:
    xls = pd.ExcelFile(uploaded_file)
    sheet = "Plant" if "Plant" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet)
    df = df.dropna(how="all").copy()
    columns = list(df.columns)
    colmap = {
        "supplier": find_col(columns, ["Supplier", "Vendor", "Hire Supplier"]),
        "description": find_col(columns, ["Description", "Item Description", "Plant Description"]),
        "fleet": find_col(columns, ["Fleet No", "Fleet", "Asset No", "Item No"]),
        "cost": find_col(columns, ["Cost", "Rate", "Weekly Rate", "Price", "Value"]),
        "delivery": find_col(columns, ["Delivery", "Delivery Cost", "Haulage", "Transport"]),
        "status": find_col(columns, ["Status"]),
        "job": find_col(columns, ["Job No", "Job", "Project No"]),
        "order": find_col(columns, ["Order Number", "Order No", "Hire No", "PO", "PO Number"]),
        "on_hire": find_col(columns, ["On Hire / Delivery Date", "On Hire Date", "Delivery Date"]),
        "off_hire": find_col(columns, ["Off Hire Date", "Actual Off Hire Date"]),
        "expected_off_hire": find_col(columns, ["Expected Off Hire Date"]),
    }

    df["__row_number"] = df.index + 2
    df["__supplier"] = df[colmap["supplier"]].apply(clean_cell) if colmap["supplier"] else ""
    df["__description"] = df[colmap["description"]].apply(clean_cell) if colmap["description"] else ""
    df["__fleet"] = df[colmap["fleet"]].apply(clean_cell) if colmap["fleet"] else ""
    df["__status"] = df[colmap["status"]].apply(clean_cell) if colmap["status"] else ""
    df["__cost"] = df[colmap["cost"]].apply(money_to_float) if colmap["cost"] else None
    df["__delivery"] = df[colmap["delivery"]].apply(money_to_float) if colmap["delivery"] else None
    if colmap["job"] or colmap["order"]:
        df["__order_ref"] = df.apply(lambda r: build_order_ref(r.get(colmap["job"], ""), r.get(colmap["order"], "")), axis=1)
    else:
        df["__order_ref"] = ""
    df["__norm_order"] = df["__order_ref"].apply(norm)
    return df, colmap


def extract_text_from_pdf(file_bytes: bytes) -> List[str]:
    if PdfReader is None:
        raise RuntimeError("PDF reader is not available. Add pypdf or PyPDF2 to requirements.txt")
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def extract_invoice_number(text: str) -> str:
    """Extract invoice number without accidentally swallowing header labels.

    The PDF text order is messy on some suppliers. Boundary, for example, returns:
    date -> invoice number -> Hire Invoice -> labels. We therefore use strict
    candidate validation and supplier-neutral fallback patterns.
    """
    text = text.replace("\xa0", " ")

    def valid(candidate: str) -> Optional[str]:
        candidate = re.sub(r"[^A-Z0-9\-/]", "", str(candidate).upper())
        if len(candidate) < 4 or len(candidate) > 24:
            return None
        bad_bits = ["INVOICE", "DATE", "ACCOUNT", "CUSTOMER", "PERIOD", "CHARGE", "TOTAL", "NUMBER", "CONTRACT", "ADDRESS"]
        if any(b in candidate for b in bad_bits):
            return None
        if candidate in ["UNKNOWN", "HIRE", "NO", "N/A"]:
            return None
        return candidate

    patterns = [
        r"Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,24})",
        r"INVOICE\s*NO\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,24})",
        r"Hire\s+Invoice\s+No\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,24})",
        r"#\s*([A-Z]{2,}[A-Z0-9\-/]{4,24})",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            cand = valid(m.group(1))
            if cand:
                return cand

    # Boundary-style PDFs often show a standalone 5/6 digit invoice number before "Hire Invoice".
    m = re.search(r"(?m)^\s*(\d{5,8})\s*$\s*\n\s*Hire\s+Invoice", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    # If labels are on separate lines, scan a few lines after an invoice label for a standalone number/code.
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines[:60]):
        if re.search(r"invoice\s*(no|number|#)", line, re.I):
            for nxt in lines[i + 1 : i + 8]:
                cand = valid(nxt)
                if cand:
                    return cand

    # Final supplier-neutral fallback: a standalone numeric invoice-like line near top of page.
    for line in lines[:25]:
        m = re.fullmatch(r"\d{5,8}", line)
        if m:
            return line
    return "Unknown"


def extract_invoice_date(text: str) -> str:
    patterns = [
        r"Invoice\s+Date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"Date\s+of\s+Invoice\s*[:\-]?\s*(\d{1,2}[-/]?[A-Z][a-z]{2}[-/]?\d{2,4})",
        r"Date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1)
    return ""


def split_pdf_into_invoices(filename: str, pages: List[str]) -> List[Dict]:
    groups = []
    current = None
    for idx, page_text in enumerate(pages, start=1):
        inv_no = extract_invoice_number(page_text)
        has_invoice_header = bool(re.search(r"invoice\s*(no\.?|number|#)", page_text, re.I))
        page_marker = re.search(r"Page\s+\d+\s*(?:/|of)\s*\d+", page_text, re.I)

        if current is None:
            current = {"source_file": filename, "invoice_number": inv_no if inv_no != "Unknown" else (re.search(r"\d{5,8}", filename).group(0) if re.search(r"\d{5,8}", filename) else "Unknown"), "pages": [idx], "text": page_text}
            continue

        # Start a new invoice only where a genuine new invoice number is found, not just continuation page text.
        current_inv = current.get("invoice_number", "Unknown")
        if has_invoice_header and inv_no != "Unknown" and inv_no != current_inv:
            groups.append(current)
            current = {"source_file": filename, "invoice_number": inv_no if inv_no != "Unknown" else (re.search(r"\d{5,8}", filename).group(0) if re.search(r"\d{5,8}", filename) else "Unknown"), "pages": [idx], "text": page_text}
        else:
            current["pages"].append(idx)
            current["text"] += "\n" + page_text
            if current_inv == "Unknown" and inv_no != "Unknown":
                current["invoice_number"] = inv_no

    if current:
        groups.append(current)
    return groups


def extract_order_refs(text: str) -> List[str]:
    refs = set()
    # Full PAS order references.
    for m in re.finditer(r"\b(P\d{3,4}[A-Z&]*\s*/\s*H\d{3,6})\b", text, re.I):
        refs.add(m.group(1).upper().replace(" ", ""))
    # Some suppliers remove slash or ampersand spacing e.g. P151MN/H7516.
    for m in re.finditer(r"\b(P\d{3,4}[A-Z&]*\s*H\d{3,6})\b", text, re.I):
        raw = m.group(1).upper().replace(" ", "")
        if "/" not in raw:
            raw = re.sub(r"(P\d{3,4}[A-Z&]*)(H\d+)", r"\1/\2", raw)
        refs.add(raw)
    return sorted(refs)


def extract_account_name_supplier(text: str) -> str:
    """
    Some invoices, especially Boundary Plant, show the clean supplier name in the
    payment details block as 'Account Name: Boundary Plant Hire Ltd'. Use this as
    a high-confidence supplier source and ignore customer/branch/address labels.
    """
    compact = re.sub(r"\s+", " ", text).strip()
    m = re.search(
        r"Account\s+Name\s*:?\s*([A-Z0-9&.,'()\-/ ]{3,90}?)(?=\s+(Sort\s+Code|Account\s+No|IBAN|Bank|Payment|VAT|$))",
        compact,
        re.I,
    )
    if not m:
        return ""
    supplier = re.sub(r"\s+", " ", m.group(1)).strip(" :-")
    if any(bad in supplier.lower() for bad in BAD_SUPPLIER_PATTERNS):
        return ""
    if len(supplier) < 4:
        return ""
    return supplier


def extract_supplier_candidate(text: str) -> str:
    # First use explicit payment block supplier if present. This catches Boundary
    # where the top/header extraction can be unreliable but the Account Name is clean.
    account_supplier = extract_account_name_supplier(text)
    if account_supplier:
        return account_supplier

    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]
    candidates = []
    for line in lines[:35]:
        low = line.lower()
        if any(bad in low for bad in BAD_SUPPLIER_PATTERNS):
            continue
        if re.fullmatch(r"[0-9\- ]+", line):
            continue
        if len(line) < 4 or len(line) > 80:
            continue
        # Strong company-style lines.
        if re.search(r"\b(ltd|limited|plc|llp|group|hire|plant|parts|equipment|specialists|services|systems|reclamation)\b", line, re.I):
            candidates.append(line)
    if candidates:
        return candidates[0]
    # Fallback: first sensible top-left/header line.
    for line in lines[:12]:
        low = line.lower()
        if not any(bad in low for bad in BAD_SUPPLIER_PATTERNS) and len(line) >= 4:
            return line
    return "Unknown"


def extract_money_values(text: str) -> List[float]:
    values = []
    for line in text.splitlines():
        low = line.lower()
        # Prefer line-level/rate values. Still include net total as low priority later if no line values match.
        matches = re.findall(r"£\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.([0-9]{2}))?", line)
        if not matches:
            # Boundary-style rows sometimes include 200.00 without £.
            if re.search(r"\b(rate|weekly|week|wk|total charge|unit price|net|value|amount|price)\b", low):
                matches = re.findall(r"\b([0-9]{1,4})(?:\.([0-9]{2}))\b", line)
        for whole, dec in matches:
            try:
                values.append(float(f"{whole.replace(',', '')}.{dec or '00'}"))
            except Exception:
                pass
    # De-dupe while preserving order.
    out = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def extract_priority_money_values(text: str) -> List[float]:
    """Extract comparable invoice rates/values globally, but avoid header/date noise.

    We deliberately do not require supplier-specific table layouts. If a full PO
    has matched the Plant tab, any proper monetary/rate value on the invoice can
    validate against the agreed Plant value. This fixes Boundary-style tables
    where weekly rates/total charges appear as plain decimals without a £ sign.
    """
    priority = []
    fallback = []
    for raw_line in text.splitlines():
        line = raw_line.replace("\xa0", " ")
        low = line.lower()
        # Ignore address/header labels that are not charge lines.
        if any(addr in low for addr in ADDRESS_TERMS):
            continue
        if re.search(r"\b(vat registration|company number|account no|sort code|telephone|postcode|page\s+\d)\b", low):
            continue

        line_vals = []

        # Currency values e.g. £425.00
        for m in re.finditer(r"£\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.([0-9]{2}))?", line):
            whole, dec = m.group(1), m.group(2) or "00"
            try:
                line_vals.append(float(f"{whole.replace(',', '')}.{dec}"))
            except Exception:
                pass

        # Plain decimal money/rate values e.g. Boundary rows: 425.00, 200.00.
        # Avoid VAT percentage values like 20.00%.
        for m in re.finditer(r"(?<![A-Z0-9/])([0-9]{1,5}\.[0-9]{2})(?!\s*%)(?![A-Z0-9/])", line):
            try:
                val = float(m.group(1))
                if 0 < val <= 100000:
                    line_vals.append(val)
            except Exception:
                pass

        if not line_vals:
            continue

        # De-prioritise final invoice/gross/VAT totals, but keep as fallback.
        if any(label in low for label in ["invoice total", "vat total", "gross", "total vat", "vat @", "vat at", "invoice total"]):
            fallback.extend(line_vals)
        else:
            priority.extend(line_vals)

    values = priority + fallback
    out = []
    for v in values:
        v = round(float(v), 2)
        if v not in out:
            out.append(v)
    return out


def has_actual_movement_charge(text: str) -> bool:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines:
        low = line.lower()
        if any(addr in low for addr in ADDRESS_TERMS):
            continue
        if any(term in low for term in MOVEMENT_TERMS):
            # only actual charge line if money or an amount/rate-like number is present.
            if re.search(r"£\s*\d|\b\d+\.\d{2}\b", line):
                return True
    return False


def classify_invoice(text: str, plant_status: str = "") -> str:
    status = plant_status.lower()
    if "operated" in status:
        return "Operated Plant"
    if "movement" in status:
        return "Movement"
    if "purchase" in status:
        return "Purchase"
    if "repair" in status or "maintenance" in status:
        return "Repair/Maintenance"
    if "damage" in status or "charge" in status:
        return "Damage/Charges"

    low = text.lower()
    movement = has_actual_movement_charge(text)
    if any(w in low for w in ["puncture", "tyre repair", "tyre fix", "repair", "service", "maintenance"]):
        return "Repair/Maintenance"
    if any(w in low for w in ["loss of hired equipment", "damage", "cleaning charge", "wear charge"]):
        return "Damage/Charges"
    if movement and re.search(r"hire|weekly|week|wk|hire period", low):
        return "Hire + Movement"
    if movement:
        return "Movement"
    if re.search(r"hire|weekly|week|wk|hire period", low):
        return "Hire"
    return "Purchase"


def find_matching_plant_rows(plant_df: pd.DataFrame, refs: List[str]) -> pd.DataFrame:
    if not refs:
        return plant_df.iloc[0:0]
    norm_refs = [norm(r) for r in refs]
    mask = plant_df["__norm_order"].isin(norm_refs)
    return plant_df[mask].copy()


def values_match(plant_values: List[float], invoice_values: List[float], tolerance: float = 0.02) -> Tuple[bool, str, Optional[float]]:
    plant_values = [round(v, 2) for v in plant_values if v is not None and not pd.isna(v) and v > 0]
    invoice_values = [round(v, 2) for v in invoice_values if v is not None and not pd.isna(v) and v > 0]
    if not plant_values:
        return False, "No agreed rate/value found on Plant tab", None
    if not invoice_values:
        return False, "No comparable rate/value found on invoice", None
    for pv in plant_values:
        for iv in invoice_values:
            if abs(pv - iv) <= tolerance:
                return True, "Rate/value matched", 0.0
            # allow tiny rounding variance for pro-rata/line totals only when extremely close.
            if pv and abs(pv - iv) / pv <= 0.005:
                return True, "Rate/value matched within rounding tolerance", round(iv - pv, 2)
    # report nearest variance.
    nearest = min((iv - pv for pv in plant_values for iv in invoice_values), key=lambda x: abs(x))
    return False, f"Price discrepancy: nearest variance £{nearest:.2f}", nearest


def reconcile_invoice(inv: Dict, plant_df: pd.DataFrame) -> Dict:
    text = inv["text"]
    refs = extract_order_refs(text)
    matched_rows = find_matching_plant_rows(plant_df, refs)

    raw_supplier = extract_supplier_candidate(text)
    plant_supplier = ""
    plant_status = ""
    plant_rate_values = []
    plant_rows = []

    if not matched_rows.empty:
        plant_supplier = clean_cell(matched_rows.iloc[0].get("__supplier", ""))
        plant_status = clean_cell(matched_rows.iloc[0].get("__status", ""))
        plant_rows = matched_rows["__row_number"].dropna().astype(int).astype(str).tolist()
        for _, row in matched_rows.iterrows():
            cost = row.get("__cost", None)
            delivery = row.get("__delivery", None)
            if cost is not None and not pd.isna(cost) and cost > 0:
                plant_rate_values.append(float(cost))
            # delivery is only a comparable value if an actual movement charge exists on invoice.
            if has_actual_movement_charge(text) and delivery is not None and not pd.isna(delivery) and delivery > 0:
                plant_rate_values.append(float(delivery))

    supplier = plant_supplier or raw_supplier
    invoice_type = classify_invoice(text, plant_status)
    invoice_values = extract_priority_money_values(text)
    net_total = None
    # Find net total/goods value for display.
    for p in [r"Goods\s+Total\s*£?\s*([0-9,]+\.\d{2})", r"NET\s*£\s*([0-9,]+\.\d{2})", r"Sub-Total\s*£?\s*([0-9,]+\.\d{2})", r"Net\s+value\s*\n?\s*([0-9,]+\.\d{2})"]:
        m = re.search(p, text, re.I)
        if m:
            net_total = money_to_float(m.group(1))
            break

    order_ref = refs[0] if refs else ""
    matched = False
    reason = ""
    variance = None

    if not refs:
        reason = "No usable order reference on invoice"
    elif matched_rows.empty:
        reason = "Order reference not found on Plant tab"
    else:
        matched, reason, variance = values_match(plant_rate_values, invoice_values)

    status = "Matched" if matched else "Unmatched"
    return {
        "PDF File": inv["source_file"],
        "Invoice Number": inv.get("invoice_number", "Unknown"),
        "Supplier": supplier,
        "Invoice Date": extract_invoice_date(text),
        "Order Reference": order_ref,
        "Reference Quality": "Full" if refs else "Missing",
        "Invoice Type": invoice_type,
        "Plant Status": plant_status,
        "Agreed Rate / Value": ", ".join(f"£{v:.2f}" for v in sorted(set(plant_rate_values))) if plant_rate_values else "",
        "Invoice Values Found": ", ".join(f"£{v:.2f}" for v in invoice_values[:12]),
        "Invoice Net Total": f"£{net_total:.2f}" if net_total is not None else "",
        "Matched Plant Row(s)": ", ".join(plant_rows),
        "Match Status": status,
        "Unmatched Reason": "" if matched else reason,
        "Variance": f"£{variance:.2f}" if variance is not None else "",
        "Pages": ", ".join(map(str, inv.get("pages", []))),
    }


def collect_invoice_records(invoice_uploads) -> List[Dict]:
    records = []
    for uploaded in invoice_uploads:
        name = uploaded.name
        data = uploaded.read()
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for member in z.namelist():
                    if member.lower().endswith(".pdf") and not member.endswith("/"):
                        pdf_bytes = z.read(member)
                        pages = extract_text_from_pdf(pdf_bytes)
                        records.extend(split_pdf_into_invoices(member.split("/")[-1], pages))
        elif name.lower().endswith(".pdf"):
            pages = extract_text_from_pdf(data)
            records.extend(split_pdf_into_invoices(name, pages))
    return records


def style_excel(writer, dfs: Dict[str, pd.DataFrame]):
    from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill("solid", fgColor="FFD400")
    black_font = Font(color="000000", bold=True)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for sheet_name, df in dfs.items():
        ws = writer.book[sheet_name]
        ws.freeze_panes = "A2"
        if df.shape[0] >= 0 and df.shape[1] > 0:
            ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = black_font
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for idx, col in enumerate(ws.columns, start=1):
            max_len = 0
            for cell in col:
                text = "" if cell.value is None else str(cell.value)
                max_len = max(max_len, len(text))
            width = min(max(max_len + 2, 10), 42)
            ws.column_dimensions[get_column_letter(idx)].width = width


def make_excel(summary_df, matched_df, unmatched_df, all_df) -> bytes:
    output = io.BytesIO()
    rules_df = pd.DataFrame({
        "Rule": [
            "Invoice-level approval: a full invoice is Matched only if the order reference and rate/value validate.",
            "Full PAS order references are required. Missing or weak references are Unmatched.",
            "Supplier is taken from the Plant row once a full order reference matches.",
            "Movement is only detected from actual charge lines with values, not from Delivery Address/Site Address labels.",
            "Global value extraction checks line rate, weekly rate, daily rate, unit price, line value, total charge and net totals.",
            "Raw Text Preview is excluded from the operational output.",
            "Excel exports use filters, frozen headers and auto-sized columns.",
        ]
    })
    dfs = {
        "Summary": summary_df,
        "Matched": matched_df,
        "Unmatched": unmatched_df,
        "All Extracted Invoices": all_df,
        "Rules": rules_df,
    }
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            df.to_excel(writer, index=False, sheet_name=sheet)
        style_excel(writer, dfs)
    return output.getvalue()


plant_file = st.file_uploader("Upload Plant workbook", type=["xlsx", "xls"])
invoice_files = st.file_uploader("Upload invoice PDFs or ZIP", type=["pdf", "zip"], accept_multiple_files=True)

run = st.button("Run reconciliation", use_container_width=True)

if run:
    if not plant_file or not invoice_files:
        st.warning("Please upload both the Plant workbook and invoice files/ZIP.")
        st.stop()
    try:
        with st.spinner("Reading Plant workbook..."):
            plant_df, colmap = load_plant_workbook(plant_file)
        with st.spinner("Reading invoice PDFs..."):
            invoice_records = collect_invoice_records(invoice_files)
        with st.spinner("Reconciling invoices..."):
            rows = [reconcile_invoice(inv, plant_df) for inv in invoice_records]
            all_df = pd.DataFrame(rows)
            if all_df.empty:
                st.warning("No invoice records could be extracted.")
                st.stop()
            matched_df = all_df[all_df["Match Status"] == "Matched"].copy()
            unmatched_df = all_df[all_df["Match Status"] == "Unmatched"].copy()

        total = len(all_df)
        matched = len(matched_df)
        unmatched = len(unmatched_df)
        match_pct = round((matched / total) * 100, 1) if total else 0.0

        summary_df = pd.DataFrame({
            "Metric": ["Total invoices", "Matched", "Unmatched", "Match percentage", "Run date/time"],
            "Value": [total, matched, unmatched, f"{match_pct}%", datetime.now().strftime("%d/%m/%Y %H:%M")],
        })

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">Total invoices</div><div class="kpi-value">{total}</div><div class="kpi-sub">Detected records</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">Matched</div><div class="kpi-value">{matched}</div><div class="kpi-sub">Approved candidates</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">Unmatched</div><div class="kpi-value">{unmatched}</div><div class="kpi-sub">Need review</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="kpi-card"><div class="kpi-label">Match %</div><div class="kpi-value">{match_pct}%</div><div class="kpi-sub">Core KPI</div></div>', unsafe_allow_html=True)

        st.markdown("### Results")
        tab1, tab2 = st.tabs(["Unmatched", "All extracted invoices"])
        with tab1:
            st.dataframe(unmatched_df, use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(all_df, use_container_width=True, hide_index=True)

        excel_bytes = make_excel(summary_df, matched_df, unmatched_df, all_df)
        st.download_button(
            "Download Excel reconciliation",
            data=excel_bytes,
            file_name=f"PAS_Reconciliation_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Something went wrong: {e}")
        st.exception(e)
else:
    st.info("Upload your Plant workbook and invoice PDFs/ZIP, then click Run reconciliation.")
