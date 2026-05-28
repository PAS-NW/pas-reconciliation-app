import io
import re
import zipfile
from pathlib import Path
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

st.set_page_config(page_title="PAS Plant Invoice Matching", layout="wide")

st.markdown(
    f"""
    <style>
    .stApp {{ background: #f5f5f5; }}
    section[data-testid="stSidebar"] {{ background: {PAS_BLACK}; color: white; }}
    section[data-testid="stSidebar"] * {{ color: white; }}
    section[data-testid="stSidebar"] div[data-testid="stImage"] {{ margin-top: -1.15rem !important; }}
    section[data-testid="stSidebar"] div[data-testid="stImage"] img {{ display:block; }}
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


st.markdown(
    """
    <style>
    /* Tighter sidebar alignment: move PAS logo nearer to the top of the hero banner */
    section[data-testid="stSidebar"] div[data-testid="stImage"] {
        margin-top: -2.35rem !important;
        margin-bottom: 1.15rem !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stImage"] img {
        display: block;
    }

    /* Small bottom-only chase animation */
    .pas-chase-stage {
        position: relative;
        width: 100%;
        height: calc(100vh - 385px);
        min-height: 500px;
        overflow: hidden;
        margin-top: 0;
        margin-bottom: -22px;
        background: transparent;
        pointer-events: none;
    }
    .pas-chase-ground {
        position: absolute;
        left: 4%;
        right: 4%;
        bottom: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, #d8d8d8 15%, #d8d8d8 85%, transparent);
        opacity: .7;
    }
    .pas-chase-runner {
        position: absolute;
        bottom: 0;
        left: -150px;
        width: 160px;
        height: 44px;
        animation: pas-drive-across 14s linear infinite;
        will-change: transform;
    }
    @keyframes pas-drive-across {
        0% { transform: translateX(-180px); }
        100% { transform: translateX(calc(100vw - 30px)); }
    }

    /* Dump truck - intentionally small and simple */
    .pas-mini-truck {
        position: absolute;
        left: 0;
        bottom: 3px;
        width: 62px;
        height: 34px;
        animation: pas-truck-bob .32s ease-in-out infinite alternate;
    }
    @keyframes pas-truck-bob {
        from { transform: translateY(0); }
        to { transform: translateY(-1.2px); }
    }
    .pas-mini-truck .truck-bed {
        position: absolute;
        left: 4px;
        top: 8px;
        width: 36px;
        height: 19px;
        background: #FFD400;
        border: 2px solid #111;
        border-radius: 3px 3px 5px 5px;
        transform: skewX(-10deg);
        box-shadow: inset 0 -3px 0 rgba(0,0,0,.16);
    }
    .pas-mini-truck .truck-bed::before {
        content: "";
        position: absolute;
        left: 1px;
        top: -8px;
        width: 36px;
        height: 8px;
        background: #FFD400;
        border: 2px solid #111;
        border-bottom: 0;
        border-radius: 3px 3px 0 0;
        transform: skewX(-18deg);
    }
    .pas-mini-truck .truck-logo {
        position: absolute;
        left: 13px;
        top: 11px;
        font-size: 10px;
        line-height: 1;
        font-weight: 1000;
        letter-spacing: -.8px;
        color: #111;
        z-index: 5;
    }
    .pas-mini-truck .truck-cab {
        position: absolute;
        left: 41px;
        top: 10px;
        width: 18px;
        height: 18px;
        background: #FFD400;
        border: 2px solid #111;
        border-radius: 3px 5px 3px 2px;
        box-shadow: inset -3px 0 0 rgba(0,0,0,.1);
    }
    .pas-mini-truck .truck-cab::before {
        content: "";
        position: absolute;
        left: 3px;
        top: 2px;
        width: 7px;
        height: 7px;
        background: #9fd0d8;
        border: 1.7px solid #111;
        border-radius: 2px;
    }
    .pas-mini-truck .truck-nose {
        position: absolute;
        left: 56px;
        top: 21px;
        width: 7px;
        height: 7px;
        background: #FFD400;
        border: 2px solid #111;
        border-left: 0;
        border-radius: 0 3px 3px 0;
    }
    .pas-mini-truck .truck-wheel {
        position: absolute;
        bottom: -1px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #111;
        animation: pas-wheel-spin .28s linear infinite;
    }
    .pas-mini-truck .truck-wheel::after {
        content: "";
        position: absolute;
        inset: 3px;
        border-radius: 50%;
        background: #FFD400;
    }
    .pas-mini-truck .wheel-one { left: 17px; }
    .pas-mini-truck .wheel-two { left: 47px; }
    @keyframes pas-wheel-spin { to { transform: rotate(360deg); } }

    .pas-mini-dust {
        position: absolute;
        left: -27px;
        bottom: 2px;
        width: 40px;
        height: 15px;
    }
    .pas-mini-dust span {
        position: absolute;
        display: block;
        border-radius: 50%;
        background: rgba(151,117,69,.22);
        animation: pas-dust-puff .72s ease-in-out infinite;
    }
    .pas-mini-dust span:nth-child(1) { width: 17px; height: 8px; left: 13px; bottom: 0; }
    .pas-mini-dust span:nth-child(2) { width: 12px; height: 6px; left: 3px; bottom: 3px; animation-delay: .16s; }
    .pas-mini-dust span:nth-child(3) { width: 8px; height: 5px; left: 28px; bottom: 4px; animation-delay: .31s; }
    @keyframes pas-dust-puff {
        0%,100% { transform: translateX(0) scale(1); opacity: .28; }
        50% { transform: translateX(-7px) scale(1.15); opacity: .68; }
    }

    .pas-mini-lines {
        position: absolute;
        width: 24px;
        height: 14px;
        opacity: .48;
    }
    .pas-mini-lines.left { left: -31px; bottom: 21px; }
    .pas-mini-lines.runner-lines { left: 76px; bottom: 17px; }
    .pas-mini-lines span {
        display: block;
        height: 1.5px;
        margin: 3px 0;
        background: #777;
        border-radius: 2px;
        animation: pas-lines .36s ease-in-out infinite alternate;
    }
    .pas-mini-lines span:nth-child(2) { width: 17px; margin-left: 6px; animation-delay: .08s; }
    .pas-mini-lines span:nth-child(3) { width: 12px; margin-left: 11px; animation-delay: .15s; }
    @keyframes pas-lines { from { transform: translateX(0); opacity: .25; } to { transform: translateX(-7px); opacity: .8; } }

    /* Stick man: cleaner, smaller and no sweat beads */
    .pas-mini-man {
        position: absolute;
        left: 105px;
        bottom: 5px;
        width: 25px;
        height: 34px;
        animation: pas-man-bounce .24s ease-in-out infinite alternate;
    }
    @keyframes pas-man-bounce { from { transform: translateY(0); } to { transform: translateY(-1.4px); } }
    .pas-mini-man .head {
        position: absolute;
        top: 0;
        left: 9px;
        width: 8px;
        height: 8px;
        background: #fff;
        border: 2px solid #111;
        border-radius: 50%;
    }
    .pas-mini-man .body,
    .pas-mini-man .arm-a,
    .pas-mini-man .arm-b,
    .pas-mini-man .leg-a,
    .pas-mini-man .leg-b {
        position: absolute;
        background: #111;
        border-radius: 5px;
        transform-origin: 50% 0;
    }
    .pas-mini-man .body { width: 3px; height: 15px; left: 13px; top: 11px; transform: rotate(8deg); }
    .pas-mini-man .arm-a { width: 3px; height: 13px; left: 13px; top: 15px; animation: pas-arm-a .28s ease-in-out infinite alternate; }
    .pas-mini-man .arm-b { width: 3px; height: 12px; left: 13px; top: 15px; animation: pas-arm-b .28s ease-in-out infinite alternate; }
    .pas-mini-man .leg-a { width: 3px; height: 15px; left: 14px; top: 25px; animation: pas-leg-a .25s ease-in-out infinite alternate; }
    .pas-mini-man .leg-b { width: 3px; height: 14px; left: 13px; top: 25px; animation: pas-leg-b .25s ease-in-out infinite alternate; }
    @keyframes pas-arm-a { from { transform: rotate(58deg); } to { transform: rotate(-48deg); } }
    @keyframes pas-arm-b { from { transform: rotate(-55deg); } to { transform: rotate(48deg); } }
    @keyframes pas-leg-a { from { transform: rotate(-57deg); } to { transform: rotate(48deg); } }
    @keyframes pas-leg-b { from { transform: rotate(52deg); } to { transform: rotate(-50deg); } }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.image("pas_logo.png", use_column_width=True)
    st.markdown("### PAS Plant Invoice Matching")
    st.markdown("Upload the Plant workbook and invoice PDFs/ZIP, then export a clean reconciliation workbook.")
    st.markdown("---")
    st.markdown("**Instructions:**")
    st.markdown("- Upload Hire Order Spreadsheet")
    st.markdown("- Upload ZIP of all invoices to be checked")
    st.markdown("- Run Reconciliation")
    st.markdown("- Download Reconciliation Spreadsheet")
    st.markdown("- Smoke Crack")

st.markdown(
    """
    <div class="pas-hero">
      <div class="pas-title">PAS Plant Invoice Matching</div>
      <div class="pas-subtitle">PAS NW Ltd · v1.0 Prototype Build</div>
    </div>
    """,
    unsafe_allow_html=True,
)

BAD_SUPPLIER_PATTERNS = [
    "invoice", "invoice no", "invoice number", "vat", "vat number", "account", "account no",
    "customer", "customer ref", "your ref", "order no", "page", "date", "due date",
    "delivery address", "site address", "ship to", "bill to", "hire period", "total charge",
    "weekly rate", "payment", "bank", "sort code", "goods total", "invoice total", "net total",
    "pas (nw)", "pas nw", "p a s", "pocket nook", "lowton", "warrington",
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


def normalize_order_ref(ref: str) -> str:
    """Normalise PAS order refs for phased job codes.

    Operational rule:
    - P153G1/H7697 and P153G2/H7697 should match P153/H7697.
    - P151M&N/H7516 or P151MN/H7516 should match P151/H7516.

    The H number remains exact; only the job-code phase suffix is stripped.
    """
    ref = clean_cell(ref).upper().replace(" ", "")
    ref = ref.replace("\\", "/")
    if not ref:
        return ""
    # Convert P153G2H7697 to P153G2/H7697 if the slash is missing.
    ref = re.sub(r"^(P\d{3,4}[A-Z0-9&]*)(H\d{3,6})$", r"\1/\2", ref)
    m = re.match(r"^(P\d{3,4})([A-Z0-9&]*)/(H\d{3,6})$", ref)
    if not m:
        return norm(ref)
    base, suffix, hire_no = m.groups()
    # Strip known phase/group suffixes. Keep this deliberately conservative.
    suffix_clean = suffix.replace("&", "")
    if suffix_clean in {"G1", "G2", "MN"}:
        return norm(f"{base}/{hire_no}")
    return norm(f"{base}{suffix}/{hire_no}")


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
    df["__norm_order"] = df["__order_ref"].apply(normalize_order_ref)
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

    # SLD / Carrier invoices often show the real number as *HI312614* while
    # "Hire Invoice No" is visually far away from the number in extracted text.
    m_hi = re.search(r"\*\s*HI\s*(\d{5,8})\s*\*", text, flags=re.IGNORECASE)
    if m_hi:
        return m_hi.group(1)

    # Filename/text style with a plain hire invoice number next to the HI marker.
    m_hi2 = re.search(r"\bHI\s*(\d{5,8})\b", text, flags=re.IGNORECASE)
    if m_hi2:
        return m_hi2.group(1)

    def valid(candidate: str) -> Optional[str]:
        candidate = re.sub(r"[^A-Z0-9\-/]", "", str(candidate).upper())
        if len(candidate) < 4 or len(candidate) > 24:
            return None
        bad_bits = ["INVOICE", "DATE", "ACCOUNT", "CUSTOMER", "PERIOD", "CHARGE", "TOTAL", "NUMBER", "CONTRACT", "ADDRESS", "SLDBOLTON", "PASNW", "PASNWLTD", "POCKET", "NOOK", "LANE", "ROAD", "STREET", "AVENUE", "WARRINGTON", "LOWTON", "ADDRESS"]
        if any(b in candidate for b in bad_bits):
            return None
        if candidate in ["UNKNOWN", "HIRE", "NO", "N/A"]:
            return None
        return candidate

    patterns = [
        r"INVOICE\s+NO\s*[:\-]\s*(\d{4,10})",
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


def bad_invoice_number(candidate: str) -> bool:
    candidate = clean_cell(candidate).upper()
    if not candidate or candidate == "UNKNOWN":
        return True
    bad_bits = [
        "INVOICE", "DATE", "ACCOUNT", "CUSTOMER", "PERIOD", "CHARGE", "TOTAL",
        "NUMBER", "CONTRACT", "ADDRESS", "POCKET", "NOOK", "LANE", "ROAD",
        "STREET", "AVENUE", "WARRINGTON", "LOWTON", "PAS", "SLDBOLTON",
        "WA31AB", "ORDER", "GREATER", "AINSCOUGH", "HAULAGE", "CHEMI",
        "ACCOUNTNO", "INVOICEDATE", "ACCOUNTNOP105"
    ]
    return any(bit in candidate for bit in bad_bits)

def invoice_number_from_filename(filename: str) -> str:
    """Return a strong invoice number from the source PDF filename.

    In practice, most single-invoice PDFs are named after the invoice number.
    This is more reliable than PDF text extraction for suppliers where labels
    are read in the wrong order, e.g. Kensite/Boundary headers.
    Multi-invoice PDFs usually have descriptive names and will not match these
    patterns, so their invoice numbers still come from page text.
    """
    raw = str(filename or "").split(" / record")[0]
    base = Path(raw).stem.upper()
    base = re.sub(r"[_]+", " ", base)

    # Strong alphanumeric invoice formats first.
    patterns = [
        r"\b(I\d{3}I\d{5,})\b",      # GSF, e.g. I261I022140
        r"\b(WIN\d{4,8})\b",          # Ashley
        r"\b(INV\d{4,9})\b",          # Fox etc
        r"\b(\d{5,8})Q\b",            # Kensite filenames like 915708Q ON SAGE
        r"\b(\d{5,8})\b",             # Boundary/RSS/SLD/SMT/Tyrefix
    ]
    for pat in patterns:
        m = re.search(pat, base)
        if m:
            return m.group(1)
    return ""


def choose_invoice_number(filename: str, extracted: str) -> str:
    file_no = invoice_number_from_filename(filename)
    extracted = clean_cell(extracted) or "Unknown"
    extracted_upper = extracted.upper()

    # If the filename contains a strong invoice number, prefer it. This avoids
    # glued header text such as INVOICEDATEACCOUNTNO and branch/customer lines.
    if file_no:
        if (
            extracted_upper == "UNKNOWN"
            or bad_invoice_number(extracted)
            or len(extracted_upper) > 18
            or not re.search(r"\d", extracted_upper)
            or extracted_upper in {"INVOICE", "HIRE INVOICE", "SALES INVOICE"}
        ):
            return file_no
        # If extracted is merely the filename number with extra junk attached, use filename.
        if extracted_upper.startswith(file_no) and extracted_upper != file_no:
            return file_no
        # For standard single-invoice files, filename is normally the safest source.
        if re.fullmatch(r"(\d{5,8}|WIN\d{4,8}|INV\d{4,9}|I\d{3}I\d{5,})", file_no):
            return file_no

    return extracted


def extract_invoice_date(text: str) -> str:
    """Extract the document invoice date, not hire/delivery/due/payment dates.

    Priority is given only to dates that sit next to strong document-date labels.
    This prevents hire-period dates such as 18/05/2026 - 24/05/2026 or due dates
    being pulled through as the invoice date.
    """
    def norm_date(raw: str) -> str:
        return clean_cell(raw).replace("  ", " ")

    date_token = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[-\s]?[A-Za-z]{3,9}[-\s]?\d{2,4})"

    compact = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    compact_patterns = [
        rf"Date\s+of\s+Invoice\s*[:\-]?\s*{date_token}",
        rf"Invoice\s+Date\s*[:\-]?\s*{date_token}",
        rf"Document\s+Date\s*[:\-]?\s*{date_token}",
        rf"Date\s*[:\-]\s*{date_token}",
    ]
    for pat in compact_patterns:
        m = re.search(pat, compact, re.I)
        if m:
            return norm_date(m.group(1))

    # Boundary text often extracts as: '24 May 2026 176607 Hire Invoice'.
    m = re.search(rf"{date_token}\s+\d{{5,8}}\s+Hire\s+Invoice", compact, re.I)
    if m:
        return norm_date(m.group(1))

    strong_patterns = [
        rf"Date\s+of\s+Invoice\s*[:\-]?\s*{date_token}",
        rf"Invoice\s+Date\s*[:\-]?\s*{date_token}",
        rf"Invoice\s+dated\s*[:\-]?\s*{date_token}",
        rf"Document\s+Date\s*[:\-]?\s*{date_token}",
    ]
    for pat in strong_patterns:
        m = re.search(pat, text, re.I)
        if m:
            return norm_date(m.group(1))

    # Some suppliers put the invoice date on the line immediately after the label.
    lines = [clean_cell(l) for l in text.splitlines() if clean_cell(l)]
    for i, line in enumerate(lines[:80]):
        if re.search(r"^(Date\s+of\s+Invoice|Invoice\s+Date|Document\s+Date)\b", line, re.I):
            window = " ".join(lines[i:i+4])
            m = re.search(date_token, window, re.I)
            if m:
                return norm_date(m.group(1))

    # Weak fallback: only accept a generic 'Date:' near the invoice header, and reject known non-document labels.
    for i, line in enumerate(lines[:60]):
        if re.search(r"\b(Due|Hire|Delivery|Collection|From|To|Payment|Period)\b", line, re.I):
            continue
        m = re.search(rf"^Date\s*[:\-]?\s*{date_token}$", line, re.I)
        if m:
            return norm_date(m.group(1))

    return ""


def split_pdf_into_invoices(filename: str, pages: List[str]) -> List[Dict]:
    groups = []
    current = None
    for idx, page_text in enumerate(pages, start=1):
        raw_inv_no = extract_invoice_number(page_text)
        inv_no = choose_invoice_number(filename, raw_inv_no)
        has_invoice_header = bool(re.search(r"invoice\s*(no\.?|number|#)", page_text, re.I))
        page_marker = re.search(r"Page\s+\d+\s*(?:/|of)\s*\d+", page_text, re.I)

        if current is None:
            current = {"source_file": filename, "invoice_number": inv_no, "pages": [idx], "text": page_text}
            continue

        # Start a new invoice only where a genuine new invoice number is found, not just continuation page text.
        current_inv = current.get("invoice_number", "Unknown")
        if has_invoice_header and inv_no != "Unknown" and inv_no != current_inv:
            groups.append(current)
            current = {"source_file": filename, "invoice_number": inv_no, "pages": [idx], "text": page_text}
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
    for m in re.finditer(r"\b(P\d{3,4}[A-Z0-9&]*\s*/\s*H\d{3,6})\b", text, re.I):
        refs.add(m.group(1).upper().replace(" ", ""))
    # Some suppliers remove slash or ampersand spacing e.g. P151MN/H7516.
    for m in re.finditer(r"\b(P\d{3,4}[A-Z0-9&]*\s*H\d{3,6})\b", text, re.I):
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


def extract_known_supplier_from_text(text: str) -> str:
    """High-confidence supplier extraction from explicit supplier identifiers.

    This is not matching logic. It only stops the app from using customer/address/table
    text as a supplier where the actual supplier name is clearly printed somewhere on
    the invoice PDF.
    """
    compact = re.sub(r"\s+", " ", text).strip()
    low = compact.lower()

    # Payment/account name blocks are usually the cleanest source.
    account_supplier = extract_account_name_supplier(text)
    if account_supplier:
        if "boundary plant" in account_supplier.lower():
            return "Boundary Plant"
        return account_supplier

    # Common printed supplier names/logos/footer identifiers.
    if "kensite" in low or "kensite services" in low:
        return "Kensite"
    if "sld bolton" in low or "sldpumpspower" in low or "carrier rental systems" in low:
        return "SLD Pumps"
    if "smiths equipment hire" in low or "smithshire" in low:
        return "Smiths Hire"
    if "ashley plant hire" in low:
        return "Ashley Plant"
    if "rope & sling specialists" in low or "rssgroup" in low:
        return "Rope & Sling Specialists Ltd"
    if "gsf car parts" in low:
        return "GSF Car Parts"
    if "tyrefix plant tyres" in low:
        return "Tyrefix Plant Tyres (UK) Ltd"
    if "fox brothers" in low or "fox group" in low:
        return "Fox Brothers"
    if "smt gb" in low or "smt.network" in low or "services machinery" in low:
        return "SMT GB"
    return ""


def extract_supplier_candidate(text: str) -> str:
    # Use high-confidence supplier identifiers before any generic header guess.
    known_supplier = extract_known_supplier_from_text(text)
    if known_supplier:
        return known_supplier

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
    norm_refs = [normalize_order_ref(r) for r in refs]
    mask = plant_df["__norm_order"].isin(norm_refs)
    return plant_df[mask].copy()


def close_money(a: float, b: float, tolerance: float = 0.02) -> bool:
    try:
        return abs(round(float(a), 2) - round(float(b), 2)) <= tolerance
    except Exception:
        return False


def extract_rate_charge_lines(text: str) -> List[Dict[str, float]]:
    """Extract structured rate/charge pairs from invoice text.

    Handles common hire invoice wording such as:
    - £18.60 per week for 1 week, 2 days ... £26.04
    - £35.00 WK 0/4/2 STD £154.00
    - Boundary-style table rows with weekly rate and total charge as plain decimals.
    """
    rows = []
    flat = re.sub(r"\s+", " ", text.replace("£ ", "£")).strip()

    def add(rate, charge=None, days=None, source=""):
        try:
            rate = round(float(str(rate).replace(",", "")), 2)
        except Exception:
            return
        if rate <= 0 or rate > 100000:
            return
        c = None
        if charge is not None:
            try:
                c = round(float(str(charge).replace(",", "")), 2)
            except Exception:
                c = None
        d = None
        if days is not None:
            try:
                d = float(days)
            except Exception:
                d = None
        if c is None and d is not None:
            c = round(rate / 5 * d, 2)
        item = {"rate": rate}
        if c is not None and c > 0:
            item["charge"] = c
        if d is not None:
            item["days"] = d
        if source:
            item["source"] = source
        if item not in rows:
            rows.append(item)

    for m in re.finditer(
        r"£\s*([0-9,]+\.\d{2})\s*per\s*week\s*for\s*"
        r"(?:(\d+)\s*week[s]?)?\s*,?\s*"
        r"(?:(\d+)\s*day[s]?)?.{0,220}?£\s*([0-9,]+\.\d{2})",
        flat, re.I
    ):
        rate = m.group(1)
        weeks = int(m.group(2) or 0)
        days = int(m.group(3) or 0)
        charge = m.group(4)
        add(rate, charge, weeks * 5 + days, "per week wording")

    for m in re.finditer(
        r"£\s*([0-9,]+\.\d{2})\s*per\s*week\s*for\s*"
        r"(?:(\d+)\s*week[s]?)?\s*,?\s*"
        r"(?:(\d+)\s*day[s]?)?",
        flat, re.I
    ):
        rate = m.group(1)
        weeks = int(m.group(2) or 0)
        days = int(m.group(3) or 0)
        if weeks or days:
            add(rate, None, weeks * 5 + days, "calculated per week wording")

    for m in re.finditer(r"£?\s*([0-9,]+\.\d{2})\s*WK\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+).{0,60}?£?\s*([0-9,]+\.\d{2})", flat, re.I):
        rate = m.group(1)
        months = int(m.group(2) or 0)
        weeks = int(m.group(3) or 0)
        days = int(m.group(4) or 0)
        charge = m.group(5)
        add(rate, charge, (months * 4 * 5) + (weeks * 5) + days, "M/W/D wording")

    for line in text.splitlines():
        low = line.lower()
        if any(addr in low for addr in ADDRESS_TERMS):
            continue
        if re.search(r"\b(invoice total|vat total|goods total|sort code|account no|payment details)\b", low):
            continue
        nums = [float(x) for x in re.findall(r"(?<![A-Z0-9/])([0-9]{1,5}\.[0-9]{2})(?!\s*%)(?![A-Z0-9/])", line)]
        if len(nums) >= 2 and re.search(r"\b(\d+\s*/\s*\d+|/\s*\d+)\b", line):
            add(nums[-2], nums[-1], None, "table row rate/charge")

    return rows


def calculated_invoice_values(text: str) -> List[float]:
    vals = []
    for item in extract_rate_charge_lines(text):
        vals.append(item.get("rate"))
        if item.get("charge") is not None:
            vals.append(item.get("charge"))
    out = []
    for v in vals:
        if v is None:
            continue
        v = round(float(v), 2)
        if v > 0 and v not in out:
            out.append(v)
    return out


def values_match(plant_values: List[float], invoice_values: List[float], line_items: Optional[List[Dict[str, float]]] = None, tolerance: float = 0.02) -> Tuple[bool, str, Optional[float]]:
    """Validate invoice values against Plant values.

    Important behaviour:
    - If structured invoice lines are found, validate the invoice as a set of lines, not one isolated rate.
    - This prevents one matching rate from approving an invoice that also has an unmatched extra charge.
    - Supports pro-rata weekly hire where invoices show "£x per week for y weeks, z days".
    - Supports combined Plant rows where invoice has multiple lines but the Plant row has one combined value.
    """
    plant_values = sorted(set(round(float(v), 2) for v in plant_values if v is not None and not pd.isna(v) and float(v) > 0))
    invoice_values = sorted(set(round(float(v), 2) for v in invoice_values if v is not None and not pd.isna(v) and float(v) > 0))
    line_items = line_items or []

    line_rates = []
    line_charges = []
    validated_prorata_lines = []

    for item in line_items:
        rate = item.get("rate")
        charge = item.get("charge")
        days = item.get("days")
        if rate is not None and float(rate) > 0:
            line_rates.append(round(float(rate), 2))
        if charge is not None and float(charge) > 0:
            line_charges.append(round(float(charge), 2))
        if rate is not None and charge is not None and days is not None:
            expected = round(float(rate) / 5 * float(days), 2)
            if close_money(expected, float(charge), 0.03):
                validated_prorata_lines.append(round(float(rate), 2))

    line_rates = sorted(set(line_rates))
    line_charges = sorted(set(line_charges))

    if not plant_values:
        return False, "No agreed rate/value found on Plant tab", None
    if not invoice_values and not line_rates and not line_charges:
        return False, "No comparable rate/value found on invoice", None

    plant_sum = round(sum(plant_values), 2)
    rate_sum = round(sum(line_rates), 2) if line_rates else None
    charge_sum = round(sum(line_charges), 2) if line_charges else None
    invoice_sum = round(sum(invoice_values), 2) if invoice_values else None

    # Structured line validation comes first. This is the key invoice-level safety check.
    if line_rates or line_charges:
        # Combined Plant row case: e.g. Excavator + forks on invoice, one combined value on Plant tab.
        if rate_sum is not None and close_money(plant_sum, rate_sum, tolerance):
            return True, "Combined invoice line rates matched Plant value", 0.0
        if charge_sum is not None and close_money(plant_sum, charge_sum, tolerance):
            return True, "Combined invoice line charges matched Plant value", 0.0

        # Pro-rata weekly hire case: invoice rates match Plant rates and line charges calculate correctly.
        if validated_prorata_lines:
            unmatched_rates = []
            for rate in line_rates:
                if not any(close_money(rate, pv, tolerance) for pv in plant_values):
                    unmatched_rates.append(rate)
            if not unmatched_rates:
                return True, "Weekly rates matched and pro-rata hire charges validated", 0.0

        # Multiple Plant rows / multiple invoice lines case: every invoice line rate must be present on Plant.
        if line_rates:
            unmatched_rates = []
            for rate in line_rates:
                if not any(close_money(rate, pv, tolerance) for pv in plant_values):
                    unmatched_rates.append(rate)
            if not unmatched_rates:
                return True, "Invoice line rates matched Plant values", 0.0
            return False, "Additional or unmatched invoice charge line found", None

    # Fallback: direct value/rate matching where no structured lines were found.
    for pv in plant_values:
        for iv in invoice_values:
            if close_money(pv, iv, tolerance):
                return True, "Rate/value matched", 0.0
            if pv and abs(pv - iv) / pv <= 0.005:
                return True, "Rate/value matched within rounding tolerance", round(iv - pv, 2)

    for comp in [x for x in [rate_sum, charge_sum, invoice_sum] if x is not None and x > 0]:
        if close_money(plant_sum, comp, tolerance):
            return True, "Combined invoice values matched Plant value", 0.0
        for pv in plant_values:
            if close_money(pv, comp, tolerance):
                return True, "Combined invoice values matched agreed value", 0.0

    nearest_candidates = invoice_values + line_rates + line_charges + [x for x in [rate_sum, charge_sum, invoice_sum] if x is not None and x > 0]
    if nearest_candidates:
        nearest = min((iv - pv for pv in plant_values for iv in nearest_candidates), key=lambda x: abs(x))
        return False, f"Price discrepancy: nearest variance £{nearest:.2f}", nearest
    return False, "No comparable rate/value found on invoice", None

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
    line_items = extract_rate_charge_lines(text)
    invoice_values = extract_priority_money_values(text)
    for v in calculated_invoice_values(text):
        if v not in invoice_values:
            invoice_values.append(v)
    net_total = None
    # Find net total/goods value for display.
    for p in [r"Goods\s+Total\s*£?\s*([0-9,]+\.\d{2})", r"NET\s*£\s*([0-9,]+\.\d{2})", r"Sub-Total\s*£?\s*([0-9,]+\.\d{2})", r"Net\s+value\s*\n?\s*([0-9,]+\.\d{2})"]:
        m = re.search(p, text, re.I)
        if m:
            net_total = money_to_float(m.group(1))
            break

    order_ref = refs[0] if refs else ""
    normalised_order_ref = normalize_order_ref(order_ref) if order_ref else ""
    matched = False
    reason = ""
    variance = None

    if not refs:
        reason = "No usable order reference on invoice"
    elif matched_rows.empty:
        reason = "Order reference not found on Plant tab"
    else:
        matched, reason, variance = values_match(plant_rate_values, invoice_values, line_items)

    status = "Matched" if matched else "Unmatched"
    return {
        "PDF File": inv["source_file"],
        "Invoice Number": inv.get("invoice_number", "Unknown"),
        "Supplier": supplier,
        "Invoice Date": extract_invoice_date(text),
        "Order Reference": order_ref,
        "Normalised Order Reference": normalised_order_ref,
        "Reference Quality": "Full" if refs else "Missing",
        "Invoice Type": invoice_type,
        "Plant Status": plant_status,
        "Agreed Rate / Value": ", ".join(f"£{v:.2f}" for v in sorted(set(plant_rate_values))) if plant_rate_values else "",
        "Invoice Values Found": ", ".join(f"£{v:.2f}" for v in invoice_values[:12]),
        "Pro-Rata Lines Found": ", ".join([f"£{x.get('rate', 0):.2f} -> £{x.get('charge', 0):.2f}" for x in line_items[:8] if x.get('charge') is not None]),
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


OUTPUT_COLUMNS = [
    "PDF File",
    "Invoice Number",
    "Supplier",
    "Order Reference",
    "Invoice Type",
    "Plant Status",
    "Agreed Rate / Value",
    "Match Status",
    "Unmatched Reason",
]


def clean_output_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = df.copy()
    for col in OUTPUT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out[OUTPUT_COLUMNS]


def make_excel(summary_df, matched_df, unmatched_df, all_df) -> bytes:
    output = io.BytesIO()
    rules_df = pd.DataFrame({
        "Rule": [
            "Invoice-level approval: a full invoice is Matched only if the order reference and rate/value validate.",
            "Full PAS order references are required. Missing or weak references are Unmatched.",
            "Supplier is taken from the Plant row once a full order reference matches.",
            "Movement is only detected from actual charge lines with values, not from Delivery Address/Site Address labels.",
            "Global value extraction checks line rate, weekly rate, daily rate, unit price, line value, total charge and net totals.",
            "Weekly hire charges are validated using pro-rata week/day calculations where the invoice shows them.",
            "Job-code phases are normalised for matching: P153G1/P153G2 become P153, and P151M&N/P151MN become P151.",
            "Raw Text Preview is excluded from the operational output.",
            "Excel exports use filters, frozen headers and auto-sized columns.",
        ]
    })
    dfs = {
        "Summary": summary_df,
        "Matched": clean_output_df(matched_df),
        "Unmatched": clean_output_df(unmatched_df),
        "All Extracted Invoices": clean_output_df(all_df),
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
            st.dataframe(clean_output_df(unmatched_df), use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(clean_output_df(all_df), use_container_width=True, hide_index=True)

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
    st.markdown(
        """
        <div class="pas-chase-stage" aria-hidden="true">
            <div class="pas-chase-ground"></div>
            <div class="pas-chase-runner">
                <div class="pas-mini-lines left"><span></span><span></span><span></span></div>
                <div class="pas-mini-dust"><span></span><span></span><span></span></div>
                <div class="pas-mini-truck">
                    <div class="truck-bed"></div>
                    <div class="truck-logo">PAS</div>
                    <div class="truck-cab"></div>
                    <div class="truck-nose"></div>
                    <div class="truck-wheel wheel-one"></div>
                    <div class="truck-wheel wheel-two"></div>
                </div>
                <div class="pas-mini-lines runner-lines"><span></span><span></span></div>
                <div class="pas-mini-man">
                    <div class="head"></div>
                    <div class="body"></div>
                    <div class="arm-a"></div>
                    <div class="arm-b"></div>
                    <div class="leg-a"></div>
                    <div class="leg-b"></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
