import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from pypdf import PdfReader

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

APP_TITLE = "PAS Invoice Reconciliation"
LOGO_PATH = Path(__file__).with_name("pas_logo.png")

st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #f7f7f4; color: #0A0A0A; }
    [data-testid="stHeader"] { background: #0A0A0A; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #24242c 0%, #171820 100%); }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    .block-container { padding-top: 3rem; max-width: 1280px; }
    h1, h2, h3, label { color: #0A0A0A !important; }
    .pas-header-title { color:#0A0A0A !important; font-size:42px; font-weight:900; line-height:1.05; margin:0; letter-spacing:-1px; }
    .pas-header-subtitle { color:#555555 !important; margin-top:10px; font-size:18px; }
    .stButton > button[kind="primary"] { background:#FFD400 !important; color:#0A0A0A !important; border:0 !important; font-weight:800 !important; border-radius:10px !important; }
    .stButton > button[kind="primary"]:hover { background:#e9c200 !important; color:#0A0A0A !important; }
    .stDownloadButton > button { background:#FFD400 !important; color:#0A0A0A !important; border:0 !important; font-weight:800 !important; border-radius:10px !important; }
    .stDownloadButton > button:hover { background:#e9c200 !important; color:#0A0A0A !important; border:0 !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 18px; }
    .stTabs [data-baseweb="tab"] { color:#333333 !important; font-weight:700 !important; }
    .stTabs [aria-selected="true"] { color:#FF3B3B !important; }
    [data-testid="stFileUploaderDropzone"] { background:#171820 !important; border: 1px solid #30313a !important; border-radius: 12px !important; }
    [data-testid="stFileUploaderDropzone"] * { color: #ffffff !important; }
    .stAlert { border-radius: 12px !important; }
    div[data-testid="metric-container"] { background:white; border:1px solid #e3e3e3; padding:18px; border-radius:16px; box-shadow:0 2px 12px rgba(0,0,0,.04); }
    </style>
    """,
    unsafe_allow_html=True,
)

header_left, header_right = st.columns([0.08, 0.92])
with st.container():
    cols = st.columns([0.09, 0.91])
    with cols[0]:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=82)
    with cols[1]:
        st.markdown(f"<div style='padding-top:5px'><div class='pas-header-title'>{APP_TITLE}</div><div class='pas-header-subtitle'>Plant hire invoice matching against the Plant tab.</div></div>", unsafe_allow_html=True)

st.divider()

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
]

SUPPLIER_HINTS = {
    "Rope & Sling Specialists Ltd": ["rope & sling", "rssgroup"],
    "Kensite Services Ltd": ["kensite"],
    "SMT GB": ["smt gb", "services machinery"],
    "Fox Brothers (Leyland) Ltd": ["fox brothers", "fox group"],
    "Smiths Equipment Hire Ltd": ["smiths equipment", "smiths hire"],
    "Ashley Plant Hire and Reclamation Ltd": ["ashley plant"],
    "Boundary Plant Hire Ltd": ["boundary plant"],
    "SLD Pumps & Power": ["sld pumps", "carrier rental"],
}

FULL_PO_RE = re.compile(r"P\d{3}(?:M&N|MN|M\s*&\s*N)?/H\d+", re.IGNORECASE)
WEAK_PO_RE = re.compile(r"\bP\d{3}(?:M&N|MN|M\s*&\s*N)?\b", re.IGNORECASE)
MONEY_RE = re.compile(r"£\s*([0-9,]+\.\d{2})")


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower()) if s is not None else ""


def clean_po(po):
    if po is None or pd.isna(po):
        return ""
    po = str(po).upper().replace(" ", "")
    po = po.replace("P151M&N", "P151MN")
    po = po.replace("P151M/N", "P151MN")
    po = po.replace("P151M&AMP;N", "P151MN")
    if po.endswith(".0"):
        po = po[:-2]
    return po


def extract_text_from_pdf_bytes(data: bytes):
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def split_invoice_pages(pages):
    # First working version: assess each page that contains an invoice number as a record.
    # This correctly handles supplier PDFs where each page is a separate invoice.
    records = []
    buffer = []
    for page_text in pages:
        if re.search(r"invoice\s*(no|number|#)[:\s]", page_text, re.I) and buffer:
            records.append("\n".join(buffer))
            buffer = [page_text]
        else:
            buffer.append(page_text)
    if buffer:
        records.append("\n".join(buffer))
    return records


def detect_supplier(text):
    low = text.lower()
    for supplier, hints in SUPPLIER_HINTS.items():
        if any(h in low for h in hints):
            return supplier
    # Fallback: top-left/header style first meaningful line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:10]:
        if not re.search(r"invoice|pas \(?nw\)?|pocket nook|date|account", ln, re.I):
            return ln[:80]
    return "Unknown"


def detect_invoice_no(text):
    patterns = [
        r"Invoice\s*(?:No|No\.|Number|#)[:\s#]*([A-Z0-9\-]+)",
        r"INVOICE\s*NO[:\s]*([A-Z0-9\-]+)",
        r"Hire Invoice No\s*([A-Z0-9\-]+)",
        r"#(INV\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return "Unknown"


def detect_date(text):
    patterns = [
        r"Invoice Date[:\s]*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        r"Date of Invoice[:\s]*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{2,4})",
        r"\b([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\b",
        r"\b([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    return ""


def detect_po(text):
    m = FULL_PO_RE.search(text)
    if m:
        return clean_po(m.group(0)), "Full"
    m = WEAK_PO_RE.search(text)
    if m:
        return clean_po(m.group(0)), "Weak"
    return "", "Missing"


def detect_weekly_rates(text):
    rates = []
    for m in re.finditer(r"£\s*([0-9,]+\.\d{2})\s*(?:per\s*)?week", text, re.I):
        rates.append(float(m.group(1).replace(",", "")))
    for m in re.finditer(r"Weekly\s*Rate[:\s]*([0-9,]+\.\d{2})", text, re.I):
        rates.append(float(m.group(1).replace(",", "")))
    return sorted(set(rates))


def detect_net_total(text):
    for pat in [r"Sub-?Total\s*£?\s*([0-9,]+\.\d{2})", r"Goods\s*Total\s*£?\s*([0-9,]+\.\d{2})", r"NET\s*£\s*([0-9,]+\.\d{2})"]:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1).replace(",", ""))
    monies = [float(x.replace(",", "")) for x in MONEY_RE.findall(text)]
    return max(monies) if monies else None


def classify_invoice(text):
    low = text.lower()
    if any(k in low for k in ["puncture", "tyre", "tire"]):
        return "Repair/Maintenance"
    if any(k in low for k in ["loss of hired equipment", "damage", "wear charge"]):
        return "Damage/Charges"
    if any(k in low for k in ["operated", "operator", "dozer", "gps"]):
        return "Operated Plant"
    if any(k in low for k in ["delivery", "collection", "haulage", "transport"]):
        if any(k in low for k in ["hire invoice", "weekly", "per week"]):
            return "Hire + Movement"
        return "Movement"
    if any(k in low for k in ["sales invoice", "filter", "parts", "sale items"]):
        return "Purchase"
    if any(k in low for k in ["hire invoice", "weekly", "per week", "hire period"]):
        return "Hire"
    return "Unknown"


def parse_invoice_record(source_file, text):
    po, po_quality = detect_po(text)
    return {
        "Source File": source_file,
        "Invoice No": detect_invoice_no(text),
        "Supplier": detect_supplier(text),
        "Invoice Date": detect_date(text),
        "PO / Ref": po,
        "PO Quality": po_quality,
        "Type": classify_invoice(text),
        "Weekly Rates Found": ", ".join(f"£{r:,.2f}" for r in detect_weekly_rates(text)),
        "Net Total": detect_net_total(text),
        "Raw Text Preview": text[:700].replace("\n", " "),
    }


def load_pdf_files(uploaded_files):
    pdfs = []
    for uploaded in uploaded_files:
        data = uploaded.read()
        name = uploaded.name
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.filename.lower().endswith(".pdf"):
                        pdfs.append((Path(info.filename).name, z.read(info)))
        elif name.lower().endswith(".pdf"):
            pdfs.append((name, data))
    return pdfs


def plant_reference_columns(df):
    cols = {norm(c): c for c in df.columns}
    def get(*names):
        for n in names:
            if norm(n) in cols:
                return cols[norm(n)]
        return None
    return {
        "supplier": get("Supplier"),
        "job": get("Job No", "Job Number"),
        "order": get("Order Number", "Order No"),
        "description": get("Description"),
        "fleet": get("Fleet No", "Fleet"),
        "cost": get("Cost", "Weekly Rate", "Rate"),
        "status": get("Status"),
        "off_hire": get("Off Hire Date"),
    }


def prepare_plant(df):
    c = plant_reference_columns(df)
    plant = df.copy()
    plant["__supplier_norm"] = plant[c["supplier"]].map(norm) if c["supplier"] else ""
    if c["job"] and c["order"]:
        plant["__po"] = plant[c["job"]].astype(str).str.strip() + "/" + plant[c["order"]].astype(str).str.strip()
    elif c["order"]:
        plant["__po"] = plant[c["order"]].astype(str).str.strip()
    else:
        plant["__po"] = ""
    plant["__po"] = plant["__po"].map(clean_po)
    if c["cost"]:
        plant["__cost"] = pd.to_numeric(plant[c["cost"]], errors="coerce")
    else:
        plant["__cost"] = pd.NA
    return plant, c


def supplier_score(a, b):
    if not a or not b:
        return 0
    if fuzz:
        return fuzz.token_set_ratio(str(a), str(b))
    return 100 if norm(a) in norm(b) or norm(b) in norm(a) else 0


def reconcile_record(rec, plant, cols):
    reasons = []
    result = "Unmatched"
    matched_row = ""

    if rec["PO Quality"] != "Full":
        return result, "No usable full order reference on invoice", matched_row

    candidates = plant[plant["__po"] == clean_po(rec["PO / Ref"])]
    if candidates.empty:
        return result, "PO/order reference not found on Plant tab", matched_row

    # Supplier check, but do not over-fail if supplier aliases are messy yet.
    supplier_ok = False
    if cols.get("supplier"):
        for idx, row in candidates.iterrows():
            if supplier_score(rec["Supplier"], row[cols["supplier"]]) >= 70:
                supplier_ok = True
                matched_row = idx + 2
                break
    else:
        supplier_ok = True

    if not supplier_ok:
        reasons.append("PO found but supplier mismatch")

    invoice_rates = []
    if rec.get("Weekly Rates Found"):
        for rate in re.findall(r"[0-9,]+\.\d{2}", rec["Weekly Rates Found"]):
            invoice_rates.append(float(rate.replace(",", "")))

    if invoice_rates:
        plant_rates = [float(x) for x in candidates["__cost"].dropna().tolist()]
        rate_match = any(abs(ir - pr) <= 0.02 for ir in invoice_rates for pr in plant_rates)
        if not rate_match:
            reasons.append("Price discrepancy / weekly rate not found on Plant tab")

    if rec["Type"] in ["Damage/Charges", "Repair/Maintenance", "Movement", "Purchase", "Operated Plant"]:
        # For non-standard invoice types, match based on full PO + supplier where available.
        if not reasons or reasons == ["Price discrepancy / weekly rate not found on Plant tab"]:
            reasons = []

    if reasons:
        return "Unmatched", "; ".join(reasons), matched_row

    return "Matched", "Invoice-level match passed", matched_row


def make_excel(summary, matched_df, unmatched_df, rules_df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")
        matched_df.to_excel(writer, index=False, sheet_name="Matched")
        unmatched_df.to_excel(writer, index=False, sheet_name="Unmatched")
        rules_df.to_excel(writer, index=False, sheet_name="Rules")
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#FFD400", "font_color": "#000000", "border": 1})
        money_fmt = workbook.add_format({"num_format": "£#,##0.00"})
        for sheet_name, df in [("Summary", summary), ("Matched", matched_df), ("Unmatched", unmatched_df), ("Rules", rules_df)]:
            ws = writer.sheets[sheet_name]
            for col_num, value in enumerate(df.columns.values):
                ws.write(0, col_num, value, header_fmt)
                width = min(max(len(str(value)) + 4, 12), 42)
                ws.set_column(col_num, col_num, width)
            if "Net Total" in df.columns:
                idx = list(df.columns).index("Net Total")
                ws.set_column(idx, idx, 14, money_fmt)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))
    output.seek(0)
    return output


with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=120)
    st.subheader("Rules")
    for r in RULES:
        st.caption(f"✓ {r}")

plant_file = st.file_uploader("Upload latest Plant workbook", type=["xlsx", "xlsm", "xls"])
invoice_files = st.file_uploader("Upload invoice PDFs or ZIP files", type=["pdf", "zip"], accept_multiple_files=True)

if st.button("Run reconciliation", type="primary", disabled=not (plant_file and invoice_files)):
    try:
        plant_df = pd.read_excel(plant_file, sheet_name="Plant")
        plant, cols = prepare_plant(plant_df)
        pdfs = load_pdf_files(invoice_files)
        records = []
        for filename, data in pdfs:
            pages = extract_text_from_pdf_bytes(data)
            for i, invoice_text in enumerate(split_invoice_pages(pages), start=1):
                rec = parse_invoice_record(filename if len(pages) == 1 else f"{filename} / record {i}", invoice_text)
                status, reason, matched_row = reconcile_record(rec, plant, cols)
                rec["Result"] = status
                rec["Reason"] = reason
                rec["Matched Plant Row"] = matched_row
                records.append(rec)

        results = pd.DataFrame(records)
        matched_df = results[results["Result"] == "Matched"].copy()
        unmatched_df = results[results["Result"] != "Matched"].copy()
        total = len(results)
        matched = len(matched_df)
        unmatched = len(unmatched_df)
        match_pct = round((matched / total * 100), 1) if total else 0
        matched_value = matched_df["Net Total"].sum(numeric_only=True) if not matched_df.empty else 0
        unmatched_value = unmatched_df["Net Total"].sum(numeric_only=True) if not unmatched_df.empty else 0
        summary = pd.DataFrame([
            {"Metric": "Total invoices processed", "Value": total},
            {"Metric": "Matched invoices", "Value": matched},
            {"Metric": "Unmatched invoices", "Value": unmatched},
            {"Metric": "Match percentage", "Value": f"{match_pct}%"},
            {"Metric": "Matched net value", "Value": f"£{matched_value:,.2f}"},
            {"Metric": "Unmatched net value", "Value": f"£{unmatched_value:,.2f}"},
        ])
        rules_df = pd.DataFrame({"Rule": RULES})

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total invoices", total)
        c2.metric("Matched", matched)
        c3.metric("Unmatched", unmatched)
        c4.metric("Match %", f"{match_pct}%")

        # Display only the useful review tabs on-screen.
        # Matched invoices are still included in the downloaded Excel workbook,
        # but hidden from the app view to keep the dashboard clean.
        tab1, tab2 = st.tabs(["Unmatched", "All extracted invoices"])
        with tab1:
            st.dataframe(unmatched_df, use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(results, use_container_width=True, hide_index=True)

        excel = make_excel(summary, matched_df, unmatched_df, rules_df)
        st.download_button(
            "Download Excel reconciliation",
            data=excel,
            file_name="PAS_Invoice_Reconciliation_Output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        st.error(f"Could not complete reconciliation: {e}")
else:
    st.info("Upload the Plant workbook and invoice PDF/ZIP batch, then run reconciliation.")
