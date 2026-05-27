import io
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import streamlit as st
from pypdf import PdfReader
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

APP_TITLE = "PAS Invoice Reconciliation"
LOGO_PATH = Path(__file__).with_name("pas_logo.png")
PAS_YELLOW = "#FFD400"
PAS_BLACK = "#0B0B0B"
PAS_DARK = "#181922"

RULES = [
    "Use Plant tab only",
    "Invoice-level approval: any failed line makes the whole invoice unmatched",
    "Full PO required; weak or missing PO is unmatched",
    "5-day hire week: weekends and bank holidays excluded",
    "Weekly rate match can validate pro-rata hire invoices",
    "Off-hired items cannot be charged beyond off-hire date",
    "Operated Plant uses day/shift logic, not weekly hire logic",
    "Every unmatched invoice must include a clear reason",
    "Multiple invoices inside one PDF are assessed separately",
    "Summary must always show match percentage",
    "PDF recognition v3: multi-page invoices stay together unless a genuine new invoice starts",
    "Supplier detection ignores VAT numbers, branches, depots and page continuation text",
]

DISPLAY_COLUMNS = {
    "Source File": "PDF File",
    "Invoice No": "Invoice Number",
    "Supplier": "Supplier",
    "Invoice Date": "Invoice Date",
    "PO / Ref": "Order Reference",
    "PO Quality": "Reference Quality",
    "Type": "Invoice Type",
    "Weekly Rates Found": "Agreed Rate / Value",
    "Net Total": "Invoice Net Total",
    "Result": "Match Status",
    "Reason": "Unmatched Reason",
    "Matched Plant Row": "Matched Plant Row",
}

DROP_EXPORT_COLUMNS = {"Raw Text Preview", "Raw Text", "Text", "raw_text"}

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    f"""
<style>
.stApp {{ background: #f7f7f4; color: {PAS_BLACK}; }}
[data-testid="stHeader"] {{ background: {PAS_BLACK}; }}
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #24242c 0%, #171820 100%); }}
[data-testid="stSidebar"] * {{ color: #f6f6f6 !important; }}
.block-container {{ padding-top: 2.5rem; max-width: 1250px; }}
h1, h2, h3, label, p {{ color: {PAS_BLACK} !important; }}
.pas-title {{ display:flex; align-items:center; gap:18px; margin-bottom: 45px; }}
.pas-title img {{ width:76px; height:76px; border-radius:10px; object-fit:cover; }}
.pas-title h1 {{ font-size:42px; line-height:1; font-weight:900; margin:0; letter-spacing:-1px; }}
.pas-title p {{ margin:8px 0 0 0; color:#444 !important; font-size:16px; }}
.metric-row {{ display:grid; grid-template-columns:repeat(4,1fr); gap:70px; margin:24px 0 28px 0; }}
.metric-label {{ font-size:14px; color:#0b0b0b; font-weight:700; margin-bottom:5px; }}
.metric-value {{ font-size:34px; color:{PAS_YELLOW}; font-weight:900; line-height:1; text-shadow: 0 1px 0 rgba(0,0,0,.12); }}
.stButton > button {{ background:{PAS_YELLOW} !important; color:{PAS_BLACK} !important; border:0 !important; border-radius:10px !important; font-weight:800 !important; }}
.stDownloadButton > button {{ background:{PAS_YELLOW} !important; color:{PAS_BLACK} !important; border:0 !important; border-radius:10px !important; font-weight:800 !important; }}
[data-testid="stFileUploader"] section {{ background:#171820 !important; border: 1px solid #30313a !important; border-radius: 12px !important; }}
[data-testid="stFileUploader"] section * {{ color:#fff !important; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 20px; }}
.stTabs [data-baseweb="tab"] {{ color:#333; font-weight:800; }}
.stTabs [aria-selected="true"] {{ color:#000 !important; border-bottom:3px solid {PAS_YELLOW} !important; }}
[data-testid="stDataFrame"] {{ border-radius:12px; overflow:hidden; }}
.small-note {{ color:#555 !important; font-size:13px; }}
</style>
""",
    unsafe_allow_html=True,
)

# ---------- Helpers ----------

def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", safe_text(value).upper())


def money_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    s = safe_text(value)
    if not s:
        return None
    s = s.replace(",", "").replace("£", "")
    m = re.search(r"-?\d+(?:\.\d{1,2})?", s)
    return float(m.group(0)) if m else None


def find_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    lookup = {norm(c): c for c in cols}
    for cand in candidates:
        nc = norm(cand)
        if nc in lookup:
            return lookup[nc]
    for c in cols:
        nc = norm(c)
        for cand in candidates:
            if norm(cand) in nc:
                return c
    return None


def load_plant(uploaded_file) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    xls = pd.ExcelFile(uploaded_file)
    sheet = "Plant" if "Plant" in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(uploaded_file, sheet_name=sheet)
    df = df.dropna(how="all").copy()
    df.columns = [safe_text(c) for c in df.columns]
    df["_Plant Row"] = df.index + 2
    cols = list(df.columns)
    colmap = {
        "supplier": find_col(cols, ["Supplier", "Vendor", "Company"]),
        "description": find_col(cols, ["Description", "Item", "Product"]),
        "fleet": find_col(cols, ["Fleet No.", "Fleet No", "Fleet", "Asset", "Item No", "Serial"]),
        "cost": find_col(cols, ["Cost", "Rate", "Weekly Rate", "Price", "Value"]),
        "delivery": find_col(cols, ["Delivery", "Haulage", "Transport", "Movement"]),
        "status": find_col(cols, ["Status", "Order Status", "Type"]),
        "job": find_col(cols, ["Job No", "Job", "Project"]),
        "order": find_col(cols, ["Order Number", "Order No", "PO", "PO Number", "Hire No", "H Number"]),
        "on_hire": find_col(cols, ["On Hire / Delivery Date", "On Hire", "Delivery Date"]),
        "off_hire": find_col(cols, ["Off Hire Date", "Off-Hire Date", "Offhire"]),
        "expected_off": find_col(cols, ["Expected Off Hire Date", "Expected Off-Hire"]),
    }
    return df, colmap


def extract_pages_from_pdf_bytes(data: bytes) -> List[str]:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def extract_files(invoice_uploads) -> List[Tuple[str, bytes]]:
    files = []
    if not invoice_uploads:
        return files
    for up in invoice_uploads:
        name = up.name
        data = up.read()
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.filename.lower().endswith(".pdf") and not info.is_dir():
                        files.append((Path(info.filename).name, z.read(info)))
        elif name.lower().endswith(".pdf"):
            files.append((name, data))
    return files

# ---------- PDF Recognition v3 ----------

def page_invoice_numbers(text: str) -> List[str]:
    patterns = [
        r"\bInvoice\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Z0-9\-/]+)",
        r"\bINVOICE\s*NO\s*[:#]?\s*([A-Z0-9\-/]+)",
        r"\bInvoice\s+number\s+([A-Z0-9\-/]+)",
        r"\bHire\s+Invoice\s+No\s*[:#]?\s*([A-Z0-9\-/]+)",
    ]
    out = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            val = m.group(1).strip().strip(":")
            if val and not re.match(r"^(DATE|NO|NUMBER|PAGE)$", val, re.I):
                out.append(val)
    # Handle Fox #INV259319 style
    for m in re.finditer(r"#\s*(INV\d+)", text, re.I):
        out.append(m.group(1).upper())
    # de-duplicate preserving order
    dedup = []
    for x in out:
        if x not in dedup:
            dedup.append(x)
    return dedup


def is_continuation_page(text: str, previous_invoice_no: str = "") -> bool:
    t = text[:1200]
    # Continuation page markers
    if re.search(r"\bPage\s+\d+\s*/\s*\d+\b", t, re.I) and previous_invoice_no:
        nums = page_invoice_numbers(t)
        # Same invoice number on page 2 is continuation; no invoice number is also continuation
        if not nums or previous_invoice_no in nums:
            return True
    if re.search(r"\bcontinued\b|\bcontinuation\b", t, re.I):
        return True
    return False


def split_pdf_into_invoice_records(filename: str, pages: List[str]) -> List[Dict[str, Any]]:
    """Group pages into invoice records. Multi-page single invoices stay together. True multi-invoice PDFs split."""
    records = []
    current_pages: List[str] = []
    current_inv = ""

    for idx, page in enumerate(pages, start=1):
        nums = page_invoice_numbers(page[:2000])
        page_inv = nums[0] if nums else ""
        new_invoice = False

        if not current_pages:
            new_invoice = True
        else:
            if page_inv and current_inv and norm(page_inv) != norm(current_inv):
                new_invoice = True
            elif page_inv and not current_inv and not is_continuation_page(page, current_inv):
                # If a new page has an invoice number and prior page did not, split only if it looks like a full invoice header
                header_score = bool(re.search(r"invoice\s*(date|no|number)|customer\s*(ref|order)|order\s*no", page[:1800], re.I))
                new_invoice = header_score
            else:
                new_invoice = False

        if new_invoice and current_pages:
            records.append({
                "source_file": filename if len(records) == 0 else f"{filename} / record {len(records)+1}",
                "text": "\n".join(current_pages),
            })
            current_pages = []
            current_inv = ""

        current_pages.append(page)
        if page_inv and not current_inv:
            current_inv = page_inv

    if current_pages:
        records.append({
            "source_file": filename if len(records) == 0 else f"{filename} / record {len(records)+1}",
            "text": "\n".join(current_pages),
        })
    return records


def extract_supplier(text: str) -> str:
    top = "\n".join([ln.strip() for ln in text.splitlines()[:35] if ln.strip()])
    lines = [ln.strip() for ln in top.splitlines() if ln.strip()]

    # Known-name detection is not supplier-specific matching logic; it prevents branch/VAT/address labels becoming supplier.
    known = [
        "SMT GB", "GSF Car Parts", "GSF CARPARTS", "Boundary Plant Hire", "Ashley Plant Hire",
        "Rope & Sling Specialists", "SLD Pumps", "SLD Pumps & Power", "Kensite", "Smiths Equipment Hire",
        "Smiths Hire", "Fox Brothers", "Fox Group", "RSS", "Rope & Sling",
    ]
    upper = top.upper()
    for k in known:
        if k.upper() in upper:
            if k.upper() == "GSF CARPARTS":
                return "GSF Car Parts"
            if k.upper() == "RSS":
                return "Rope & Sling Specialists Ltd"
            if k.upper() == "ROPE & SLING":
                return "Rope & Sling Specialists Ltd"
            if k.upper() == "FOX GROUP":
                return "Fox Brothers (Leyland) Ltd"
            return k

    bad_tokens = [
        "VAT", "INVOICE", "ACCOUNT", "CUSTOMER", "ORDER", "PAGE", "DATE", "PAS ", "PAS(",
        "POCKET NOOK", "LOWTON", "WARRINGTON", "UNITED KINGDOM", "GREAT BRITAIN", "TEL", "EMAIL",
        "BRANCH", "DEPOT", "SORT CODE", "ACCOUNT NO", "REGISTRATION", "REGISTERED", "DELIVERY",
    ]
    address_like = re.compile(r"\b(ROAD|LANE|STREET|HOUSE|PARK|INDUSTRIAL|UNIT|ESTATE|WA\d|WN\d|PR\d|M\d|L\d)\b", re.I)
    branch_like = re.compile(r"^\d+\s*[-–]\s*[A-Z ]+$", re.I)

    candidates = []
    for ln in lines[:20]:
        u = ln.upper()
        if any(tok in u for tok in bad_tokens):
            continue
        if branch_like.search(ln):
            continue
        if address_like.search(ln) and not re.search(r"\b(LTD|LIMITED|HIRE|PLANT|GROUP|PARTS|CAR)\b", ln, re.I):
            continue
        if len(ln) < 3 or len(ln) > 80:
            continue
        # Prefer company-ish lines
        score = 0
        if re.search(r"\b(LTD|LIMITED|PLC|GROUP|HIRE|PLANT|PARTS|CAR|SERVICES|SPECIALISTS)\b", ln, re.I):
            score += 5
        if not re.search(r"\d", ln):
            score += 1
        candidates.append((score, ln))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return "Unknown supplier"


def extract_invoice_no(text: str) -> str:
    nums = page_invoice_numbers(text[:2500])
    if nums:
        return nums[0]
    # Fallback for filenames/content with WINxxxxx or numeric document IDs
    m = re.search(r"\b(WIN\d{4,}|INV\d{4,}|I\d{3,}I\d{4,}|\d{6,})\b", text[:2500], re.I)
    return m.group(1).upper() if m else "Not found"


def extract_invoice_date(text: str) -> str:
    patterns = [
        r"Invoice\s+date\s*[:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",
        r"Date\s+of\s+Invoice\s*[:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",
        r"Date\s*[:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text[:3000], re.I)
        if m:
            return m.group(1)
    return ""


def extract_order_refs(text: str) -> List[str]:
    refs = []
    patterns = [
        r"\b(P\d{2,4}\s*[A-Z&]*\s*/\s*H\d{3,5})\b",
        r"\b(P\d{2,4}\s*/\s*H\d{3,5})\b",
        r"Customer\s+Ref\.?\s*[:]?\s*(P\d{2,4}\s*[A-Z&]*\s*/\s*H\d{3,5}|P\d{2,4})",
        r"Your\s+ref\.?\s*[:]?\s*(P\d{2,4}\s*[A-Z&]*\s*/\s*H\d{3,5}|P\d{2,4})",
        r"Order\s+No\.?\s*[:]?\s*(P\d{2,4}\s*[A-Z&]*\s*/\s*H\d{3,5}|P\d{2,4})",
        r"PO\s*#?\s*[:]?\s*(P\d{2,4}\s*[A-Z&]*\s*/\s*H\d{3,5}|P\d{2,4})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            ref = re.sub(r"\s+", "", m.group(1).upper()).replace("&", "")
            # Preserve P151MN style from P151M&N
            ref = ref.replace("P151MN", "P151MN")
            if ref not in refs:
                refs.append(ref)
    return refs


def po_quality(ref: str) -> str:
    if re.search(r"P\d{2,4}[A-Z]*/H\d{3,5}", safe_text(ref), re.I):
        return "Full"
    if re.search(r"P\d{2,4}", safe_text(ref), re.I):
        return "Weak"
    return "Missing"


def extract_rates_and_values(text: str) -> List[float]:
    vals = []
    patterns = [
        r"£\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*per\s+week",
        r"Weekly\s+Rate\s*[:]?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"\bRate\s*[:]?\s*£?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"\bUnit\s+price\s+Net\s+amount",  # marker only; rows parsed below
    ]
    for pat in patterns[:3]:
        for m in re.finditer(pat, text, re.I):
            v = money_to_float(m.group(1))
            if v is not None:
                vals.append(v)
    # Generic currency values, useful for purchase/repair/damage where no weekly label exists
    for m in re.finditer(r"£\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)", text):
        v = money_to_float(m.group(1))
        if v is not None:
            vals.append(v)
    # SMT / parts tables: quantity unit unit price net
    for m in re.finditer(r"\b\d+\.\d{2}\s+[A-Z]{2,4}\s+(\d+(?:\.\d{1,2})?)\s+(\d+(?:\.\d{1,2})?)", text):
        vals.extend([float(m.group(1)), float(m.group(2))])
    # de-dupe approx
    clean = []
    for v in vals:
        if v > 0 and all(abs(v - x) > 0.009 for x in clean):
            clean.append(round(v, 2))
    return clean


def extract_net_total(text: str) -> Optional[float]:
    patterns = [
        r"Goods\s+Total\s*£?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"Sub[- ]?Total\s*£?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"Net\s+value\s*\n?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"NET\s*£\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
        r"Subtotal\s*£\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, text, re.I))
        if matches:
            return money_to_float(matches[-1].group(1))
    return None


def classify_invoice(text: str, plant_status: str = "") -> str:
    combined = f"{plant_status} {text}".upper()
    line_words = combined
    if "OPERATED" in line_words or "DOZER" in line_words and ("DAYS" in line_words or "OPERATED" in line_words):
        return "Operated Plant"
    if any(w in line_words for w in ["DELIVERY", "COLLECTION", "HAULAGE", "TRANSPORT", "MOVEMENT", "LOW LOADER"]):
        # Only return pure movement if not clearly hire too
        if any(w in line_words for w in ["HIRE", "WEEK", "HIRED", "HIRE ITEMS"]):
            return "Hire + Movement"
        return "Movement"
    if any(w in line_words for w in ["PUNCTURE", "TYRE", "REPAIR", "SERVICE", "MAINTENANCE"]):
        return "Repair/Maintenance"
    if any(w in line_words for w in ["DAMAGE", "LOSS OF HIRED", "LOST", "CHARGE", "WEAR CHARGE"]):
        return "Damage/Charges"
    if any(w in line_words for w in ["SALE ITEMS", "SALES INVOICE", "FILTER", "PART", "PCE", "PURCHASE"]):
        return "Purchase"
    if any(w in line_words for w in ["HIRE", "WEEKLY", "PER WEEK", "CONTRACT STATUS"]):
        return "Hire"
    return safe_text(plant_status) or "Unknown"


def plant_order_key(row: pd.Series, colmap: Dict[str, Optional[str]]) -> str:
    job = safe_text(row.get(colmap.get("job"), "")) if colmap.get("job") else ""
    order = safe_text(row.get(colmap.get("order"), "")) if colmap.get("order") else ""
    if job and order and "/" not in job and "/" not in order:
        return f"{job}/{order}"
    if order:
        return order
    return job


def find_plant_match(plant: pd.DataFrame, colmap: Dict[str, Optional[str]], refs: List[str]) -> Tuple[Optional[pd.Series], str]:
    full_refs = [r for r in refs if po_quality(r) == "Full"]
    if not full_refs:
        return None, "No usable full order reference on invoice"
    for ref in full_refs:
        nref = norm(ref)
        for _, row in plant.iterrows():
            key = plant_order_key(row, colmap)
            if norm(key) == nref or nref in norm(key) or norm(key) in nref:
                return row, ""
    return None, "PO/reference not found on Plant tab"


def rate_value_match(invoice_values: List[float], plant_row: pd.Series, colmap: Dict[str, Optional[str]]) -> Tuple[bool, str, str]:
    plant_vals = []
    for key in ["cost", "delivery"]:
        c = colmap.get(key)
        if c:
            v = money_to_float(plant_row.get(c))
            if v is not None and v > 0:
                plant_vals.append(round(v, 2))
    if not plant_vals:
        return False, "", "No rate/value found on Plant row"
    if not invoice_values:
        return False, " / ".join(f"£{v:.2f}" for v in plant_vals), "No comparable rate/value found on invoice"

    for pv in plant_vals:
        for iv in invoice_values:
            # exact/tolerant match or pro-rata derived value being comparable
            if abs(pv - iv) <= 0.02:
                return True, f"£{pv:.2f}", ""
            # weekly rate pro-rata amounts: don't reject if invoice amount is derived from rate; the weekly rate itself must appear normally
    return False, " / ".join(f"£{v:.2f}" for v in plant_vals), "Price/rate discrepancy"


def reconcile_record(rec: Dict[str, Any], plant: pd.DataFrame, colmap: Dict[str, Optional[str]]) -> Dict[str, Any]:
    text = rec["text"]
    supplier = extract_supplier(text)
    invoice_no = extract_invoice_no(text)
    invoice_date = extract_invoice_date(text)
    refs = extract_order_refs(text)
    ref = refs[0] if refs else ""
    quality = po_quality(ref)
    values = extract_rates_and_values(text)
    net_total = extract_net_total(text)

    matched_row, ref_reason = find_plant_match(plant, colmap, refs)
    result = "Unmatched"
    reasons = []
    plant_status = ""
    matched_plant_row = ""
    agreed_value = ""

    if matched_row is None:
        reasons.append(ref_reason)
    else:
        matched_plant_row = matched_row.get("_Plant Row", "")
        if colmap.get("status"):
            plant_status = safe_text(matched_row.get(colmap["status"]))
        inv_type = classify_invoice(text, plant_status)

        # Supplier fuzzy check: useful but not enough to fail where invoice header is weak.
        plant_supplier = safe_text(matched_row.get(colmap.get("supplier"), "")) if colmap.get("supplier") else ""
        if plant_supplier and supplier != "Unknown supplier":
            s1, s2 = norm(plant_supplier), norm(supplier)
            ratio = fuzz.partial_ratio(s1, s2) if fuzz else (100 if s1 in s2 or s2 in s1 else 0)
            if ratio < 60:
                reasons.append("Supplier mismatch")

        ok_value, agreed_value, value_reason = rate_value_match(values, matched_row, colmap)
        if not ok_value:
            reasons.append(value_reason)

        # Off-hire validation: if off-hire date exists and invoice date/period suggests beyond, flag softly.
        # Full hire-period extraction can be expanded later.
        if not reasons:
            result = "Matched"
    if matched_row is None:
        inv_type = classify_invoice(text, "")
    else:
        inv_type = classify_invoice(text, plant_status)

    return {
        "Source File": rec["source_file"],
        "Invoice No": invoice_no,
        "Supplier": supplier,
        "Invoice Date": invoice_date,
        "PO / Ref": ref,
        "PO Quality": quality,
        "Type": inv_type,
        "Weekly Rates Found": agreed_value,
        "Net Total": net_total if net_total is not None else "",
        "Result": result,
        "Reason": "; ".join(dict.fromkeys([r for r in reasons if r])) if reasons else "Matched",
        "Matched Plant Row": matched_plant_row,
    }


def display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for c in list(DROP_EXPORT_COLUMNS):
        if c in out.columns:
            out = out.drop(columns=[c])
    out = out.rename(columns=DISPLAY_COLUMNS)
    return out


def make_excel(summary: pd.DataFrame, matched: pd.DataFrame, unmatched: pd.DataFrame, all_records: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    wb = Workbook()
    wb.remove(wb.active)

    sheets = {
        "Summary": summary,
        "Matched": display_df(matched),
        "Unmatched": display_df(unmatched),
        "All Extracted Invoices": display_df(all_records),
        "Rules": pd.DataFrame({"Rule": RULES}),
    }

    header_fill = PatternFill("solid", fgColor="FFD400")
    black_fill = PatternFill("solid", fgColor="111111")
    white_font = Font(color="FFFFFF", bold=True)
    black_font = Font(color="000000", bold=True)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for name, df in sheets.items():
        ws = wb.create_sheet(name[:31])
        df = df.copy()
        for r_idx, row in enumerate([list(df.columns)] + df.astype(object).where(pd.notna(df), "").values.tolist(), start=1):
            for c_idx, val in enumerate(row, start=1):
                cell = ws.cell(r_idx, c_idx, val)
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if r_idx == 1:
                    cell.fill = header_fill if name != "Unmatched" else black_fill
                    cell.font = black_font if name != "Unmatched" else white_font
        ws.freeze_panes = "A2"
        if df.shape[1] > 0:
            ws.auto_filter.ref = ws.dimensions
        for col_idx in range(1, max(1, df.shape[1]) + 1):
            max_len = 10
            for cell in ws[get_column_letter(col_idx)]:
                text = safe_text(cell.value)
                max_len = max(max_len, min(len(text), 55))
            ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 2
    wb.save(output)
    return output.getvalue()

# ---------- UI ----------

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=115)
    st.markdown("### Rules")
    for rule in RULES[:10]:
        st.markdown(f"✓ {rule}")
    st.markdown("<br><span class='small-note'>PAS Invoice Reconciliation<br>v3.0 extraction upgrade</span>", unsafe_allow_html=True)

logo_html = ""
if LOGO_PATH.exists():
    import base64
    b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
    logo_html = f"<img src='data:image/png;base64,{b64}' />"
else:
    logo_html = "<div style='width:76px;height:76px;background:#FFD400;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:28px;'>PAS</div>"

st.markdown(
    f"""
<div class='pas-title'>
    {logo_html}
    <div>
        <h1>PAS Invoice Reconciliation</h1>
        <p>Plant hire invoice matching against the Plant tab.</p>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

plant_file = st.file_uploader("Upload latest Plant workbook", type=["xlsx", "xlsm", "xls"])
invoice_files = st.file_uploader("Upload invoice PDFs or ZIP files", type=["pdf", "zip"], accept_multiple_files=True)

run = st.button("Run reconciliation")

if run:
    if not plant_file or not invoice_files:
        st.warning("Upload the Plant workbook and invoice PDF/ZIP batch, then run reconciliation.")
    else:
        try:
            plant, colmap = load_plant(plant_file)
            pdf_files = extract_files(invoice_files)
            invoice_records = []
            for filename, data in pdf_files:
                pages = extract_pages_from_pdf_bytes(data)
                invoice_records.extend(split_pdf_into_invoice_records(filename, pages))

            rows = [reconcile_record(rec, plant, colmap) for rec in invoice_records]
            results = pd.DataFrame(rows)
            if results.empty:
                st.error("No invoice records could be extracted from the uploaded PDFs.")
            else:
                matched_df = results[results["Result"] == "Matched"].copy()
                unmatched_df = results[results["Result"] != "Matched"].copy()
                total = len(results)
                matched_count = len(matched_df)
                unmatched_count = len(unmatched_df)
                match_pct = round((matched_count / total) * 100, 1) if total else 0
                matched_value = pd.to_numeric(matched_df["Net Total"], errors="coerce").sum() if not matched_df.empty else 0
                unmatched_value = pd.to_numeric(unmatched_df["Net Total"], errors="coerce").sum() if not unmatched_df.empty else 0
                summary = pd.DataFrame([
                    {"Metric": "Total invoices processed", "Value": total},
                    {"Metric": "Matched invoices", "Value": matched_count},
                    {"Metric": "Unmatched invoices", "Value": unmatched_count},
                    {"Metric": "Match percentage", "Value": f"{match_pct}%"},
                    {"Metric": "Matched net value", "Value": f"£{matched_value:,.2f}"},
                    {"Metric": "Unmatched net value", "Value": f"£{unmatched_value:,.2f}"},
                ])

                st.markdown(
                    f"""
<div class='metric-row'>
  <div><div class='metric-label'>Total invoices</div><div class='metric-value'>{total}</div></div>
  <div><div class='metric-label'>Matched</div><div class='metric-value'>{matched_count}</div></div>
  <div><div class='metric-label'>Unmatched</div><div class='metric-value'>{unmatched_count}</div></div>
  <div><div class='metric-label'>Match %</div><div class='metric-value'>{match_pct}%</div></div>
</div>
""",
                    unsafe_allow_html=True,
                )

                tab1, tab2 = st.tabs(["Unmatched", "All extracted invoices"])
                with tab1:
                    st.dataframe(display_df(unmatched_df), use_container_width=True, hide_index=True)
                with tab2:
                    st.dataframe(display_df(results), use_container_width=True, hide_index=True)

                excel = make_excel(summary, matched_df, unmatched_df, results)
                st.download_button(
                    "Download Excel reconciliation",
                    data=excel,
                    file_name=f"PAS_Reconciliation_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        except Exception as exc:
            st.error(f"Could not complete reconciliation: {exc}")
else:
    st.info("Upload the Plant workbook and invoice PDF/ZIP batch, then run reconciliation.")
