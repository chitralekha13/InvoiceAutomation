import logging
import json
import os
import re
import threading
import io
from datetime import datetime

import azure.functions as func
import openpyxl
import psycopg2
import psycopg2.extras
from shared.helpers import upload_excel_to_sharepoint,upload_sync_report_to_sharepoint

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MIN_TOKEN_LEN = 2          # skip single-char initials like "J."
SUFFIX_RE  = re.compile(
    r'\b(jr\.?|sr\.?|ii|iii|iv|ph\.?d\.?|md|esq\.?|cpa)\b', re.I)
PREFIX_RE  = re.compile(
    r'\b(mr\.?|mrs\.?|ms\.?|dr\.?|prof\.?)\b', re.I)

# Columns expected in the Excel file (case-insensitive match performed at runtime)
COL_FIRST      = 'first name'
COL_LAST       = 'last name'
COL_APPROVAL   = 'approval status'
COL_HOURS      = 'hour(s)'          # fallback: 'hours'
COL_FROM       = 'from time'        # used to derive pay period month
COL_DATE       = 'date'             # alternative pay-period column
COL_DIVISION   = 'division'
COL_CLIENT     = 'client name'
COL_PROJECT    = 'project name'

# ── Entry point ───────────────────────────────────────────────────────────────

def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("sync-excel triggered")

    # ── 1. Get uploaded file ─────────────────────────────────────────────────
    try:
        file_bytes = _get_file_bytes(req)
    except ValueError as e:
        return _err(400, str(e))

    filename = req.params.get('filename') or 'timesheet.xlsx'

    # ── 2. Save to SharePoint in background thread ───────────────────────────
    sp_thread = threading.Thread(
        target=_save_to_sharepoint,
        args=(file_bytes, filename),
        daemon=True
    )
    sp_thread.start()

    # ── 3. Parse Excel ────────────────────────────────────────────────────────
    try:
        rows = _parse_excel(file_bytes)
    except Exception as e:
        logger.error("Excel parse error: %s", e)
        return _err(400, f"Could not parse Excel file: {e}")

    if not rows:
        return _err(400, "Excel file contained no data rows.")

    # 4. Load Pending invoices from DB
    try:
        conn   = _get_db_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT invoice_id, resource_name, start_date, end_date,
                vendor_hours, approval_status, division, client_name, project_name_excel
            FROM   invoices
            WHERE  LOWER(approval_status) = 'pending'
        """)
        invoices = cursor.fetchall()

    # 5. Group Excel rows by person + month
        groups  = _group_rows(rows)

    # 6. Match & update
        results = []
        for (first, last, yr, mo), group in groups.items():
            result = _process_group(first, last, yr, mo, group, invoices, cursor, conn)
            results.append(result)

    except Exception as e:
        logger.error("DB error: %s", e)
        return _err(500, f"Database error: {e}")
    finally:
        try: cursor.close()
        except: pass
        try: conn.close()
        except: pass

    # 7. Return summary 
    # 7. Generate comparison report if there are unmatched/ambiguous results
    sp_thread.join(timeout=2)

    unmatched_ambiguous = [r for r in results if r['status'] in ('UNMATCHED', 'AMBIGUOUS')]
    if unmatched_ambiguous:
        report_thread = threading.Thread(
            target=_upload_comparison_report,
            args=(unmatched_ambiguous, results, invoices, filename),
            daemon=True
        )
        report_thread.start()

    summary = {
        "processed":    len(results),
        "matched":      sum(1 for r in results if r['status'] == 'MATCHED'),
        "need_approval":sum(1 for r in results if r['status'] == 'NEED_APPROVAL'),
        "pending":      sum(1 for r in results if r['status'] == 'PENDING'),
        "unmatched":    sum(1 for r in results if r['status'] == 'UNMATCHED'),
        "ambiguous":    sum(1 for r in results if r['status'] == 'AMBIGUOUS'),
        "skipped_not_pending": sum(1 for r in results if r['status'] == 'SKIPPED_NOT_PENDING'),
        "details":      results
    }
    return func.HttpResponse(
        json.dumps(summary),
        status_code=200,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"}
    )


# File extraction

def _get_file_bytes(req: func.HttpRequest) -> bytes:
    """
    Accept the file either as:
      - multipart/form-data  (standard browser upload)
      - raw binary body      (direct POST with Content-Type: application/octet-stream)
    """
    content_type = req.headers.get('Content-Type', '')

    if 'multipart/form-data' in content_type:
        files = req.files
        if not files:
            raise ValueError("No file found in multipart request.")
        key  = next(iter(files))
        data = files[key].read()
        if not data:
            raise ValueError("Uploaded file is empty.")
        return data

    # Raw binary body
    data = req.get_body()
    if not data:
        raise ValueError("Request body is empty. Send the Excel file as binary body "
                         "or as multipart/form-data.")
    return data


# Excel parsing 

def _parse_excel(file_bytes: bytes) -> list:
    """
    Parse the Excel file and return a list of row dicts with normalised keys.
    Handles any column ordering by matching headers case-insensitively.
    """
    wb  = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws  = wb.active

    headers = []
    rows    = []

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            headers = [str(c).strip().lower() if c is not None else '' for c in row]
            continue

        if all(c is None for c in row):
            continue    # skip blank rows

        record = dict(zip(headers, row))
        rows.append(record)

    wb.close()
    return rows


# Grouping 

def _group_rows(rows: list) -> dict:
    """
    Group timesheet rows by (normalised_first, normalised_last, year, month).
    Derives year+month from 'From time' or 'Date' column (whichever is present).
    Returns dict keyed by (first, last, year, month) → list of row dicts.
    """
    groups = {}

    for row in rows:
        first = _get_col(row, COL_FIRST)
        last  = _get_col(row, COL_LAST)
        if not first and not last:
            continue

        # Derive pay period month/year
        yr, mo = _extract_month_year(row)
        if yr is None:
            yr, mo = 0, 0   # group together rows with no date

        key = (
            _normalise(first),
            _normalise(last),
            yr,
            mo
        )
        groups.setdefault(key, []).append(row)

    return groups


def _extract_month_year(row: dict):
    """Try several column names to get a month+year from the row."""
    for col in (COL_FROM, COL_DATE, 'to time', 'pay period start', 'period'):
        val = _get_col(row, col)
        if val:
            dt = _parse_date(val)
            if dt:
                return dt.year, dt.month
    return None, None


def _parse_date(val):
    if isinstance(val, datetime):
        return val
    if hasattr(val, 'year'):        # date object
        return val
    s = str(val).strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s[:10], fmt)
        except ValueError:
            pass
    return None


# Name normalisation & regex matching

def _normalise(name: str) -> str:
    s = (name or '').lower()
    s = PREFIX_RE.sub('', s)
    s = SUFFIX_RE.sub('', s)
    s = re.sub(r"[-'\u2018\u2019\u201a\u201b`]", ' ', s)
    s = re.sub(r'[^a-z\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _tokenise(name: str) -> list:
    return [t for t in _normalise(name).split() if len(t) >= MIN_TOKEN_LEN]


def _any_token_in(tokens: list, normed_db: str) -> bool:
    return any(re.search(r'\b' + re.escape(t) + r'\b', normed_db) for t in tokens)


def _match_invoice(first: str, last: str, invoices: list):
    """
    Regex token matching.
    Returns (invoice, status) where status is one of:
      MATCHED | NEED_APPROVAL | AMBIGUOUS | UNMATCHED
    """
    first_toks = _tokenise(first)
    last_toks  = _tokenise(last)

    # Pass 1: both first AND last token found in DB name
    full = [
        inv for inv in invoices
        if (db := _normalise(inv['resource_name'] or ''))
        and _any_token_in(first_toks, db)
        and _any_token_in(last_toks,  db)
    ]
    if len(full) == 1:
        return full[0], 'MATCHED'
    if len(full) > 1:
        return None, 'AMBIGUOUS'

    # Pass 2: partial match (one side only)
    partial = [
        inv for inv in invoices
        if (db := _normalise(inv['resource_name'] or ''))
        and (_any_token_in(first_toks, db) or _any_token_in(last_toks, db))
    ]
    if len(partial) == 1:
        return partial[0], 'NEED_APPROVAL'
    if len(partial) > 1:
        return None, 'AMBIGUOUS'

    return None, 'UNMATCHED'


# Pay period check 

def _pay_period_matches(invoice, year: int, month: int) -> bool:
    """
    Returns True if the invoice's pay_period_start falls in the same month+year
    as the timesheet rows.  year=0/month=0 means the timesheet had no date → skip check.
    """
    if year == 0:
        return True     # no date in timesheet — don't block on period

    for field in ('start_date', 'end_date'):
        val = invoice.get(field)
        if val:
            dt = _parse_date(str(val))
            if dt and dt.year == year and dt.month == month:
                return True
    return False


# Core processing 

def _process_group(first, last, yr, mo, group, invoices, cursor, conn) -> dict:
    """
    For one person+month group:
      1. Match to a Pending invoice
      2. Check pay period
      3. Evaluate approval statuses across all rows
      4. Write update if warranted
    """
    inv, match_status = _match_invoice(first, last, invoices)

    base = {
        'excel_name': f"{first} {last}",
        'excel_first': first,   
        'excel_last':  last,
        'year': yr,
        'month': mo,
        'row_count': len(group)
    }

    if match_status in ('UNMATCHED', 'AMBIGUOUS'):
        return {**base, 'status': match_status, 'invoice_id': None}

    # Guard: invoice must still be Pending
    current_status = (inv.get('approval_status') or '').strip().lower()
    if current_status != 'pending':
        return {**base,
                'status': 'SKIPPED_NOT_PENDING',
                'invoice_id': str(inv['invoice_id']),
                'db_status': inv.get('approval_status')}

    # Pay period check
    if not _pay_period_matches(inv, yr, mo):
        return {**base,
                'status': 'PERIOD_MISMATCH',
                'invoice_id': str(inv['invoice_id']),
                'invoice_period_start': str(inv.get('start_date', ''))}

    # Evaluate approval across all rows in this group
    approval_vals = [
        (_get_col(r, COL_APPROVAL) or '').strip().lower()
        for r in group
    ]
    all_approved = all(v == 'approved' for v in approval_vals)
    has_approved = any(v == 'approved' for v in approval_vals)
    has_non_approved = any(v != 'approved' for v in approval_vals)

    # Collect extra dimension fields from the group (take first non-empty value)
    division     = _first_val(group, COL_DIVISION)
    client_name  = _first_val(group, COL_CLIENT)
    project_name_excel = _first_val(group, COL_PROJECT)

    if all_approved:
        total_hours = sum(
            float(_get_col(r, COL_HOURS) or _get_col(r, 'hours') or 0)
            for r in group
        )
        vendor_hrs  = float(inv.get('vendor_hours') or 0)
        hours_match = abs(total_hours - vendor_hrs) < 0.01

        new_status  = 'Complete' if hours_match else 'Need Approval'
        _write_update(cursor, conn, inv['invoice_id'], {
            'approved_hours':  total_hours,
            'approval_status': new_status,
            'division':        division,
            'client_name':     client_name,
            'project_name_excel':    project_name_excel,
        })
        return {**base,
                'status':         'MATCHED',
                'invoice_id':   str(inv['invoice_id']),
                'approved_hours': total_hours,
                'vendor_hours':   vendor_hrs,
                'new_db_status':  new_status,
                'matched_to':     inv.get('resource_name')}

    elif has_approved and has_non_approved:
        # Mixed → flag but still write dimension fields
        _write_update(cursor, conn, inv['invoice_id'], {
            'approval_status': 'Need Approval',
            'division':        division,
            'client_name':     client_name,
            'project_name_excel':    project_name_excel,
        })
        return {**base,
                'status':        'NEED_APPROVAL',
                'invoice_id':  str(inv['invoice_id']),
                'new_db_status': 'Need Approval',
                'matched_to':    inv.get('resource_name')}

    else:
        # All still Pending — update dimensions only, leave approval_status
        _write_update(cursor, conn, inv['invoice_id'], {
            'division':    division,
            'client_name': client_name,
            'project_name_excel':project_name_excel,
        })
        return {**base,
                'status':       'PENDING',
                'invoice_id': str(inv['invoice_id']),
                'matched_to':   inv.get('resource_name')}


# DB helpers

def _get_db_conn():
    """Get PostgreSQL database connection"""
    conn_str = os.environ.get('SQL_CONNECTION_STRING')
    if not conn_str:
        raise ValueError("SQL_CONNECTION_STRING not found in environment")
    return psycopg2.connect(conn_str)


def _write_update(cursor, conn, invoice_id, fields: dict):
    """Build a dynamic UPDATE for only the provided fields."""
    # Remove None values
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return

    set_clause = ', '.join(f"{col} = %s" for col in fields)
    values     = list(fields.values()) + [invoice_id]

    cursor.execute(
        f"UPDATE invoices SET {set_clause}, excel_updated_at = NOW() WHERE invoice_id = %s",
        values
    )
    conn.commit()


# SharePoint upload

def _save_to_sharepoint(file_bytes: bytes, filename: str):
    """
    Upload the Excel file to SharePoint using the existing certificate-based
    context from shared/helpers.py.  Runs in a background thread so it does
    not block the HTTP response.  Errors are logged, not re-raised.
    """
    try:
        folder = os.environ.get('SP_FOLDER_PATH', 'Timesheet')
        url    = upload_excel_to_sharepoint(file_bytes, filename, folder)
        if url:
            logger.info("SharePoint upload OK: %s → %s", filename, url)
        else:
            logger.warning("SharePoint upload completed but returned no URL for: %s", filename)
    except Exception as e:
        logger.error("SharePoint upload error for '%s': %s", filename, e)


# Utility

def _get_col(row: dict, col_name: str) -> str:
    """Case-insensitive column lookup."""
    key = col_name.lower()
    for k, v in row.items():
        if k.lower() == key and v is not None:
            return str(v).strip()
    return ''


def _first_val(group: list, col_name: str) -> str:
    """Return the first non-empty value for a column across a group of rows."""
    for row in group:
        val = _get_col(row, col_name)
        if val:
            return val
    return None


def _err(code: int, msg: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({'error': msg}),
        status_code=code,
        mimetype='application/json',
        headers={"Access-Control-Allow-Origin": "*"}
    )

# Comparison report

# Comparison report

def _generate_comparison_report(unmatched_results: list, all_results: list, db_invoices: list, source_filename: str) -> bytes:
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    hdr_font  = Font(name='Arial', bold=True, color='FFFFFF', size=11)
    thin      = Side(style='thin', color='CCCCCC')
    border    = Border(left=thin, right=thin, top=thin, bottom=thin)
    center    = Alignment(horizontal='center', vertical='center')
    wrap      = Alignment(wrap_text=True, vertical='top')

    def fill(hex_color):
        return PatternFill('solid', start_color=hex_color)

    def write_header(ws, row_num, labels, hex_color):
        for c, label in enumerate(labels, 1):
            cell = ws.cell(row=row_num, column=c, value=label)
            cell.font, cell.fill, cell.alignment, cell.border = hdr_font, fill(hex_color), center, border

    def style_cell(cell, hex_color=None):
        cell.alignment, cell.border = wrap, border
        if hex_color:
            cell.fill = fill(hex_color)

    # ── Sheet 1: Unmatched / Ambiguous ───────────────────────────────────────
    ws1 = wb.active
    ws1.title = 'Unmatched & Ambiguous'
    ws1.freeze_panes = 'A3'

    ws1.merge_cells('A1:H1')
    t = ws1['A1']
    t.value = f"Sync Comparison Report  |  Source: {source_filename}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t.font, t.fill, t.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws1.row_dimensions[1].height = 22

    cols1 = ['Status', 'Excel Name (From Timesheet)', 'Year', 'Month', 'Row Count',
             'Possible DB Match', 'DB Invoice ID', 'Issue / Action Required']
    write_header(ws1, 2, cols1, 'C0392B')

    status_colors = {'UNMATCHED': 'FADBD8', 'AMBIGUOUS': 'FDEBD0'}
    status_notes  = {
        'UNMATCHED': 'No pending invoice found — check spelling or add invoice to DB',
        'AMBIGUOUS': 'Multiple invoices matched this name — resolve duplicates in DB',
    }

    for r_idx, result in enumerate(unmatched_results, start=3):
        status = result.get('status', '')
        fc     = status_colors.get(status, 'FFFFFF')

        first_toks = _tokenise(result.get('excel_first', ''))
        last_toks  = _tokenise(result.get('excel_last', ''))
        possible = [
            inv['resource_name'] for inv in db_invoices
            if (db := _normalise(inv['resource_name'] or ''))
            and (_any_token_in(first_toks, db) or _any_token_in(last_toks, db))
        ]

        row_data = [
            status,
            result.get('excel_name', ''),
            result.get('year') or '',
            result.get('month') or '',
            result.get('row_count', ''),
            ', '.join(possible) if possible else '— no partial match —',
            result.get('invoice_id') or 'N/A',
            status_notes.get(status, ''),
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws1.cell(row=r_idx, column=c_idx, value=val), fc)

    for col, width in zip('ABCDEFGH', [14, 30, 8, 8, 10, 30, 14, 50]):
        ws1.column_dimensions[get_column_letter(ord(col) - 64)].width = width

    # ── Sheet 2: All Pending DB Invoices ─────────────────────────────────────
    ws2 = wb.create_sheet('Pending DB Invoices')
    ws2.freeze_panes = 'A3'

    ws2.merge_cells('A1:H1')
    t2 = ws2['A1']
    t2.value = f"All Pending Invoices in DB  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t2.font, t2.fill, t2.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws2.row_dimensions[1].height = 22

    cols2 = ['Invoice ID', 'Resource Name', 'Start Date', 'End Date',
             'Vendor Hours', 'Approval Status', 'Division', 'Client Name']
    write_header(ws2, 2, cols2, '2980B9')

    for r_idx, inv in enumerate(db_invoices, start=3):
        row_data = [
            str(inv.get('invoice_id', '')),
            inv.get('resource_name', ''),
            str(inv.get('start_date') or ''),
            str(inv.get('end_date') or ''),
            inv.get('vendor_hours', ''),
            inv.get('approval_status', ''),
            inv.get('division', ''),
            inv.get('client_name', ''),
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws2.cell(row=r_idx, column=c_idx, value=val))

    for col, width in zip('ABCDEFGH', [14, 30, 13, 13, 13, 16, 18, 26]):
        ws2.column_dimensions[get_column_letter(ord(col) - 64)].width = width

    # Sheet 3: Matched 
    matched_results = [r for r in all_results if r['status'] == 'MATCHED']

    ws3 = wb.create_sheet('Matched')
    ws3.freeze_panes = 'A3'

    ws3.merge_cells('A1:I1')
    t3 = ws3['A1']
    t3.value = f"Matched Invoices  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t3.font, t3.fill, t3.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws3.row_dimensions[1].height = 22

    cols3 = ['Excel Name', 'Matched To (DB)', 'Invoice ID', 'Year', 'Month',
             'Approved Hours', 'Vendor Hours', 'New DB Status', 'Row Count']
    write_header(ws3, 2, cols3, '27AE60')

    for r_idx, result in enumerate(matched_results, start=3):
        row_data = [
            result.get('excel_name', ''),
            result.get('matched_to', ''),
            result.get('invoice_id') or 'N/A',
            result.get('year') or '',
            result.get('month') or '',
            result.get('approved_hours', ''),
            result.get('vendor_hours', ''),
            result.get('new_db_status', ''),
            result.get('row_count', ''),
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws3.cell(row=r_idx, column=c_idx, value=val), 'EAFAF1')

    for col, width in zip('ABCDEFGHI', [28, 28, 14, 8, 8, 15, 13, 16, 10]):
        ws3.column_dimensions[get_column_letter(ord(col) - 64)].width = width
    
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _upload_comparison_report(unmatched_results: list, all_results: list, db_invoices: list, source_filename: str):
    try:
        report_bytes = _generate_comparison_report(unmatched_results, all_results, db_invoices, source_filename)
        ts           = datetime.now().strftime('%Y%m%d_%H%M')
        report_name  = f"sync_report_{ts}.xlsx"

        url = upload_sync_report_to_sharepoint(report_bytes, report_name)

        if url:
            logger.info("Comparison report uploaded: %s → %s", report_name, url)
        else:
            logger.warning("Comparison report upload returned no URL for: %s", report_name)
    except Exception as e:
        logger.error("Comparison report upload failed: %s", e)