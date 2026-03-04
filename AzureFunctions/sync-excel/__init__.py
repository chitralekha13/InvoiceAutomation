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

    # 1. Get uploaded file
    try:
        file_bytes = _get_file_bytes(req)
    except ValueError as e:
        return _err(400, str(e))

    filename = req.params.get('filename') or 'timesheet.xlsx'
    
    # Add timestamp to filename to prevent replacement
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name_parts = filename.rsplit('.', 1)
    if len(name_parts) == 2:
        timestamped_filename = f"{name_parts[0]}_{timestamp}.{name_parts[1]}"
    else:
        timestamped_filename = f"{filename}_{timestamp}"

    # 2. Save to SharePoint in background thread
    sp_thread = threading.Thread(
        target=_save_to_sharepoint,
        args=(file_bytes, timestamped_filename),
        daemon=True
    )
    sp_thread.start()

    # ── 3. Parse Excel ────────────────────────────────────────────────────────
    try:
        rows = _parse_excel(file_bytes)
    except Exception as e:
        #logger.error("Excel parse error: %s", e)
        return _err(400, f"Could not parse Excel file: {e}")

    if not rows:
        return _err(400, "Excel file contained no data rows.")

    # 4. Load Pending invoices from DB
    try:
        conn   = _get_db_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT invoice_id, resource_name, start_date, end_date,
                invoice_hours, approval_status, division, client_name, project_name_excel
            FROM   invoices
            WHERE  LOWER(approval_status) = 'pending'
            AND  invoice_hours IS NOT NULL
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
            args=(unmatched_ambiguous, results, invoices, timestamped_filename, groups),
            daemon=True
        )
        report_thread.start()

    summary = {
        "processed":    len(results),
        "matched":      sum(1 for r in results if r['status'] == 'MATCHED'),
        "need_approval":sum(1 for r in results if r['status'] == 'Need Approval'),
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

    groups = {}

    for row in rows:
        first = _get_col(row, COL_FIRST)
        last  = _get_col(row, COL_LAST)
        if not first and not last:
            continue

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

    for col in (COL_DATE,'date'):
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
    for fmt in ('%d/%m/%Y','%d-%m-%Y','%Y-%m-%d','%Y/%m/%d','%m/%d/%Y','%d/%m/%Y',):
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

# Pay period check 

def _pay_period_matches(invoice, year: int, month: int) -> bool:

    #if year == 0:
    #   return True     # no date in timesheet — don't block on period

    for field in ('start_date', 'end_date'):
        val = invoice.get(field)
        if val:
            dt = _parse_date(str(val))
            if dt and dt.year == year and dt.month == month:
                return True
    return False

def _match_invoice(first: str, last: str, invoices: list):
    """
    Returns (invoice, status) where status is one of:
    MATCHED       — both first and last name found in DB resource_name
    Need Approval — only first OR last name found
    AMBIGUOUS     — multiple invoices matched
    PERIOD_MISMATCH — name found in DB but under a different month
    UNMATCHED     — no match found
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
        return partial[0], 'Need Approval'
    if len(partial) > 1:
        return None, 'AMBIGUOUS'

    return None, 'UNMATCHED'



# Core processing 

def _process_group(first, last, yr, mo, group, invoices, cursor, conn) -> dict:

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

    if all_approved and match_status == 'MATCHED':
        total_hours = sum(_to_float((_get_col(r, COL_HOURS) or _get_col(r, 'hours') or '0').strip()) for r in group)
        vendor_hrs = _to_float(str(inv.get('invoice_hours') or '0').strip())
        hours_match = abs(total_hours - vendor_hrs) < 0.5

        new_status  = 'Approved' if hours_match else 'Need Approval'

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
                'invoice_hours':   vendor_hrs,
                'new_db_status':  new_status,
                'matched_to':     inv.get('resource_name')}
    
    # Case 2: Partial name match (first OR last only)
    # Update hours and flag for manual review
    elif match_status == 'Need Approval':
        total_hours = sum(
            _to_float((_get_col(r, COL_HOURS) or _get_col(r, 'hours') or '0').strip())
            for r in group
        )
        logger.info("=== NEED APPROVAL (PARTIAL NAME) === Person: %s %s | Hours: %s | Invoice: %s",
                    first, last, total_hours, inv['invoice_id'])

        _write_update(cursor, conn, inv['invoice_id'], {
            'approval_status':    'Need Approval',
            'approved_hours':     total_hours,
            'division':           division,
            'client_name':        client_name,
            'project_name_excel': project_name_excel,
        })
        return {**base,
                'status':         'Need Approval',
                'invoice_id':     str(inv['invoice_id']),
                'approved_hours': total_hours,
                'new_db_status':  'Need Approval',
                'matched_to':     inv.get('resource_name')}
    
    #Case 3: Both names matched + mixed approval (some approved, some not)
    elif has_approved and has_non_approved:
        # Mixed → flag but still write dimension fields
        _write_update(cursor, conn, inv['invoice_id'], {
            'approval_status': 'Need Approval',
            'division':        division,
            'client_name':     client_name,
            'project_name_excel':    project_name_excel,
        })
        return {**base,
                'status':        'Need Approval',
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

def _generate_comparison_report(unmatched_results: list, all_results: list, db_invoices: list, source_filename: str, groups: dict) -> bytes:
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

    # Calculate total hours for each category
    matched_results = [r for r in all_results if r['status'] == 'MATCHED']
    
    total_hours_matched = sum(_to_float(r.get('approved_hours', 0)) for r in matched_results)
    
    # Calculate unmatched hours from the groups
    total_hours_unmatched = 0
    for result in unmatched_results:
        key = (result.get('excel_first', ''), result.get('excel_last', ''), 
               result.get('year', 0), result.get('month', 0))
        group = groups.get(key, [])
        for row in group:
            hours = _to_float((_get_col(row, COL_HOURS) or _get_col(row, 'hours') or '0').strip())
            total_hours_unmatched += hours
    
    total_hours_pending = sum(_to_float(inv.get('invoice_hours', 0) or 0) for inv in db_invoices)

    # ── Sheet 1: Summary (Quality Check) ─────────────────────────────────────
    ws_summary = wb.active
    ws_summary.title = 'Summary'
    
    ws_summary.merge_cells('A1:C1')
    t_sum = ws_summary['A1']
    t_sum.value = f"Excel Sync Status - Quality Check Summary  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t_sum.font = Font(name='Arial', bold=True, size=14, color='FFFFFF')
    t_sum.fill = fill('34495E')
    t_sum.alignment = center
    ws_summary.row_dimensions[1].height = 25

    # Summary data
    summary_data = [
        ('Source File', source_filename, ''),
        ('Upload Time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ''),
        ('', '', ''),
        ('Category', 'Total Hours', 'Description'),
        ('Pending DB Invoices', f'{total_hours_pending:.2f}', 'All pending invoices in database'),
        ('Matched Data', f'{total_hours_matched:.2f}', 'Successfully matched and approved from Excel'),
        ('Unmatched Data', f'{total_hours_unmatched:.2f}', 'Excel entries with no DB match'),
        ('', '', ''),
        ('Total Matched Hours', f'{total_hours_matched:.2f}', 'Hours processed from timesheet'),
        ('Total Unmatched Hours', f'{total_hours_unmatched:.2f}', 'Hours not matched to DB'),
        ('Total Pending Hours', f'{total_hours_pending:.2f}', 'Hours awaiting approval in DB'),
    ]

    for r_idx, (label, value, desc) in enumerate(summary_data, start=2):
        if r_idx == 2 or r_idx == 9:  # Empty rows (adjusted for new upload time row)
            continue
        
        cell_a = ws_summary.cell(row=r_idx, column=1, value=label)
        cell_b = ws_summary.cell(row=r_idx, column=2, value=value)
        cell_c = ws_summary.cell(row=r_idx, column=3, value=desc)
        
        if r_idx == 5:  # Header row (adjusted for new row)
            cell_a.font = cell_b.font = cell_c.font = hdr_font
            cell_a.fill = cell_b.fill = cell_c.fill = fill('5DADE2')
            cell_a.alignment = cell_b.alignment = cell_c.alignment = center
        elif r_idx in [10, 11, 12]:  # Total rows (adjusted for new row)
            cell_a.font = Font(name='Arial', bold=True, size=11)
            cell_b.font = Font(name='Arial', bold=True, size=11)
            cell_a.fill = cell_b.fill = cell_c.fill = fill('D5F4E6')
        elif r_idx in [3, 4]:  # Source file and upload time rows
            cell_a.font = Font(name='Arial', bold=True, size=10)
            cell_b.font = Font(name='Arial', size=10)
        else:
            cell_a.alignment = cell_c.alignment = wrap
        
        cell_a.border = cell_b.border = cell_c.border = border

    ws_summary.column_dimensions['A'].width = 25
    ws_summary.column_dimensions['B'].width = 18
    ws_summary.column_dimensions['C'].width = 45

    # ── Sheet 2: Pending DB Invoices ─────────────────────────────────────────
    ws2 = wb.create_sheet('Pending DB')
    ws2.freeze_panes = 'A3'

    ws2.merge_cells('A1:H1')
    t2 = ws2['A1']
    t2.value = f"All Pending Invoices in DB  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t2.font, t2.fill, t2.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws2.row_dimensions[1].height = 22

    cols2 = ['Invoice ID', 'Resource Name', 'Start Date', 'End Date',
             'Invoice Hours', 'Approval Status', 'Division', 'Client Name']
    write_header(ws2, 2, cols2, '2980B9')

    for r_idx, inv in enumerate(db_invoices, start=3):
        row_data = [
            str(inv.get('invoice_id', '')),
            inv.get('resource_name', ''),
            str(inv.get('start_date') or ''),
            str(inv.get('end_date') or ''),
            inv.get('invoice_hours', ''),
            inv.get('approval_status', ''),
            inv.get('division', ''),
            inv.get('client_name', ''),
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws2.cell(row=r_idx, column=c_idx, value=val))

    for col, width in zip('ABCDEFGH', [14, 30, 13, 13, 13, 16, 18, 26]):
        ws2.column_dimensions[get_column_letter(ord(col) - 64)].width = width

    # ── Sheet 3: Matched ─────────────────────────────────────────────────────
    ws3 = wb.create_sheet('Matched')
    ws3.freeze_panes = 'A3'

    ws3.merge_cells('A1:I1')
    t3 = ws3['A1']
    t3.value = f"Matched Invoices  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t3.font, t3.fill, t3.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws3.row_dimensions[1].height = 22

    cols3 = ['Excel Name', 'Matched To (DB)', 'Invoice ID', 'Year', 'Month',
             'Approved Hours', 'Invoice Hours', 'New DB Status', 'Row Count']
    write_header(ws3, 2, cols3, '27AE60')

    for r_idx, result in enumerate(matched_results, start=3):
        row_data = [
            result.get('excel_name', ''),
            result.get('matched_to', ''),
            result.get('invoice_id') or 'N/A',
            result.get('year') or '',
            result.get('month') or '',
            result.get('approved_hours', ''),
            result.get('invoice_hours', ''),
            result.get('new_db_status', ''),
            result.get('row_count', ''),
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws3.cell(row=r_idx, column=c_idx, value=val), 'EAFAF1')

    for col, width in zip('ABCDEFGHI', [28, 28, 14, 8, 8, 15, 13, 16, 10]):
        ws3.column_dimensions[get_column_letter(ord(col) - 64)].width = width

    # ── Sheet 4: Unmatched / Ambiguous ───────────────────────────────────────
    # ── Sheet 4: Unmatched / Ambiguous ───────────────────────────────────────
    ws1 = wb.create_sheet('Unmatched')
    ws1.freeze_panes = 'A3'

    ws1.merge_cells('A1:J1')
    t = ws1['A1']
    t.value = f"Sync Comparison Report  |  Source: {source_filename}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    t.font, t.fill, t.alignment = Font(name='Arial', bold=True, size=12, color='FFFFFF'), fill('2C3E50'), center
    ws1.row_dimensions[1].height = 22

    cols1 = ['Status', 'Excel Name (From Timesheet)', 'Year', 'Month', 'Row Count',
             'Hours (Approved)', 'Hours (Pending)', 'Hours (Other)', 'Total Hours', 'Possible DB Match']
    write_header(ws1, 2, cols1, 'C0392B')

    status_colors = {'UNMATCHED': 'FADBD8', 'AMBIGUOUS': 'FDEBD0'}

    for r_idx, result in enumerate(unmatched_results, start=3):
        status = result.get('status', '')
        fc     = status_colors.get(status, 'FFFFFF')

        # Get the group of rows for this person
        key = (result.get('excel_first', ''), result.get('excel_last', ''), 
               result.get('year', 0), result.get('month', 0))
        group = groups.get(key, [])
        
        # Calculate hours by approval status
        hours_by_status = {}
        for row in group:
            approval = (_get_col(row, COL_APPROVAL) or 'Other').strip().lower()
            if approval == 'approved':
                approval_key = 'Approved'
            elif approval == 'pending':
                approval_key = 'Pending'
            else:
                approval_key = 'Other'
            
            hours = _to_float((_get_col(row, COL_HOURS) or _get_col(row, 'hours') or '0').strip())
            hours_by_status[approval_key] = hours_by_status.get(approval_key, 0) + hours
        
        hours_approved = hours_by_status.get('Approved', 0)
        hours_pending = hours_by_status.get('Pending', 0)
        hours_other = hours_by_status.get('Other', 0)
        total_hours = hours_approved + hours_pending + hours_other

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
            f'{hours_approved:.2f}' if hours_approved > 0 else '',
            f'{hours_pending:.2f}' if hours_pending > 0 else '',
            f'{hours_other:.2f}' if hours_other > 0 else '',
            f'{total_hours:.2f}',
            ', '.join(possible) if possible else '— no db match —',
        ]
        for c_idx, val in enumerate(row_data, 1):
            style_cell(ws1.cell(row=r_idx, column=c_idx, value=val), fc)

    for col, width in zip('ABCDEFGHIJ', [14, 30, 8, 8, 10, 15, 15, 13, 12, 35]):
        ws1.column_dimensions[get_column_letter(ord(col) - 64)].width = width
    
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _upload_comparison_report(unmatched_results: list, all_results: list, db_invoices: list, source_filename: str, groups: dict):
    try:
        report_bytes = _generate_comparison_report(unmatched_results, all_results, db_invoices, source_filename, groups)
        ts           = datetime.now().strftime('%Y%m%d_%H%M')
        report_name  = f"sync_report_{ts}.xlsx"

        url = upload_sync_report_to_sharepoint(report_bytes, report_name)

        if url:
            logger.info("Comparison report uploaded: %s → %s", report_name, url)
        else:
            logger.warning("Comparison report upload returned no URL for: %s", report_name)
    except Exception as e:
        logger.error("Comparison report upload failed: %s", e)

from decimal import Decimal

def _to_float(val) -> float:
    """Safely convert DB numeric/Decimal/string to float."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return 0.0