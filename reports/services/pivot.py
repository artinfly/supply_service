import io
import os
import re
import zipfile

from .excel import xlsx_response


def _xe(s):
    if s is None:
        return ''
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def build_advances_xlsx(rows, year):
    def fv(v):
        return float(v) if v is not None else 0.0

    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'static', 'reports', 'files', 'templateIGK.xlsx'
    )

    with zipfile.ZipFile(template_path) as z_src:
        orig_s2 = z_src.read('xl/worksheets/sheet2.xml').decode('utf-8')
        orig_ss = z_src.read('xl/sharedStrings.xml').decode('utf-8')

    cols_xml = re.search(r'<cols>.*?</cols>', orig_s2, re.DOTALL).group()
    orig_ss = orig_ss.replace('2025', year)
    tmpl_sis = re.findall(r'<si>.*?</si>', orig_ss, re.DOTALL)
    tmpl_strs = re.findall(r'<t[^>]*>(.*?)</t>', orig_ss)
    tmpl_count = len(tmpl_strs)
    total_rows = len(rows) + 1

    col_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']
    hdr_styles = ['27', '1', '1', '1', '1', '1', '1', '1', '1', '4', '4']
    dat_styles = ['28', '18', '18', '18', '18', '18', '18', '19', '20', '21', '22']
    txt_fields = ['igk', 'c_agent', 'cfo', 'contract', 'state', 'payment_type', 'item', 'qty']

    ss_list = []
    ss_map = {}

    def ss_idx(val):
        s = '' if val is None else str(val)
        if s not in ss_map:
            ss_map[s] = tmpl_count + len(ss_list)
            ss_list.append(s)
        return ss_map[s]

    spec_hdr = f'Сумма по спецификации на {year} год'
    spec_hdr_idx = tmpl_strs.index(spec_hdr) if spec_hdr in tmpl_strs else ss_idx(spec_hdr)
    hdr_indices = [0, 1, 2, 3, 4, 5, 6, 9, spec_hdr_idx, 10, 11]

    data_vals = [
        ([ss_idx(row[f]) for f in txt_fields], fv(row['spec_sum']), fv(row['advance_plan']), fv(row['advance_fact']))
        for row in rows
    ]

    new_ss = '\n'.join([
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        f' count="{tmpl_count + 8 * len(rows)}" uniqueCount="{tmpl_count + len(ss_list)}">',
        *tmpl_sis,
        *[f'<si><t{" xml:space=\"preserve\"" if sv.startswith(" ") or sv.endswith(" ") else ""}>{_xe(sv)}</t></si>' for sv in ss_list],
        '</sst>',
    ]).encode('utf-8')

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' mc:Ignorable="x14ac" xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac">',
        '<sheetPr><outlinePr summaryRight="0"/><pageSetUpPr autoPageBreaks="0" fitToPage="1"/></sheetPr>',
        f'<dimension ref="A1:K{total_rows}"/>',
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<selection activeCell="A1" sqref="A1"/></sheetView></sheetViews>',
        '<sheetFormatPr defaultColWidth="10.5" defaultRowHeight="11.45" customHeight="1" x14ac:dyDescent="0.2"/>',
        cols_xml, '<sheetData>',
        '<row r="1" spans="1:11" ht="26.1" customHeight="1" x14ac:dyDescent="0.2">',
        *[f'<c r="{col}1" s="{s}" t="s"><v>{idx}</v></c>' for idx, s, col in zip(hdr_indices, hdr_styles, col_letters)],
        '</row>',
        *[
            line
            for ri, (txt_idx, spec_sum, adv_plan, adv_fact) in enumerate(data_vals, 2)
            for line in [
                f'<row r="{ri}" spans="1:11" ht="12" customHeight="1" x14ac:dyDescent="0.2">',
                *[f'<c r="{col}{ri}" s="{s}" t="s"><v>{idx}</v></c>' for idx, s, col in zip(txt_idx, dat_styles[:8], col_letters[:8])],
                f'<c r="I{ri}" s="{dat_styles[8]}"><v>{spec_sum}</v></c>',
                f'<c r="J{ri}" s="{dat_styles[9]}"><v>{adv_plan}</v></c>',
                f'<c r="K{ri}" s="{dat_styles[10]}"><v>{adv_fact}</v></c>',
                '</row>',
            ]
        ],
        '</sheetData>',
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>',
        '</worksheet>',
    ]
    new_s2 = '\n'.join(xml_lines).encode('utf-8')

    empty_records = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<pivotCacheRecords xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0"/>'
    ).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(template_path, 'r') as z_src:
        content_types = z_src.read('[Content_Types].xml').decode('utf-8')
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z_out:
            for item in z_src.infolist():
                if item.filename == 'xl/worksheets/sheet2.xml':
                    z_out.writestr(item.filename, new_s2)
                elif item.filename == 'xl/sharedStrings.xml':
                    z_out.writestr(item.filename, new_ss)
                elif item.filename == '[Content_Types].xml':
                    z_out.writestr(item.filename, content_types.encode('utf-8'))
                elif item.filename == 'xl/worksheets/sheet1.xml':
                    s1 = z_src.read(item.filename).decode('utf-8')
                    s1 = re.sub(
                        r'<row r="(?:[1-9]|1[0-9]|2[01])"[^>]*hidden="1"[^>]*>.*?</row>',
                        '', s1, flags=re.DOTALL
                    )
                    z_out.writestr(item.filename, s1.encode('utf-8'))
                elif item.filename == 'xl/styles.xml':
                    sxml = z_src.read(item.filename).decode('utf-8')
                    inner = re.search(r'<cellXfs[^>]*>(.*?)</cellXfs>', sxml, re.DOTALL).group(1).strip()
                    parts = [p for p in re.split(r'(?=<xf )', inner) if p.strip().startswith('<xf')]
                    if len(parts) > 28:
                        old28 = parts[28]
                        new28 = re.sub(r'fillId="\d+"', 'fillId="2"', old28)
                        if 'applyFill' not in new28:
                            new28 = new28.replace('<xf ', '<xf applyFill="1" ', 1)
                        sxml = sxml.replace(old28, new28, 1)
                    z_out.writestr(item.filename, sxml.encode('utf-8'))
                elif item.filename == 'xl/pivotCache/pivotCacheDefinition1.xml':
                    pcd = z_src.read(item.filename).decode('utf-8')
                    pcd = re.sub(r'(?<!\w:)ref="[^"]*"', f'ref="A1:K{total_rows}"', pcd, count=1)
                    pcd = re.sub(r'recordCount="\d+"', 'recordCount="0"', pcd)
                    pcd = pcd.replace('2025', year)
                    pcd = re.sub(r'refreshOnLoad="[01]"', 'refreshOnLoad="1"', pcd)
                    if 'refreshOnLoad' not in pcd:
                        pcd = pcd.replace('<pivotCacheDefinition ', '<pivotCacheDefinition refreshOnLoad="1" ', 1)
                    z_out.writestr(item.filename, pcd.encode('utf-8'))
                elif item.filename == 'xl/pivotCache/pivotCacheRecords1.xml':
                    z_out.writestr(item.filename, empty_records)
                elif item.filename == 'xl/pivotTables/pivotTable1.xml':
                    pt_xml = z_src.read(item.filename).decode('utf-8')
                    pt_xml = re.sub(r'(?<!\w:)ref="[^"]*"', f'ref="A1:L{total_rows}"', pt_xml, count=1)
                    pt_xml = pt_xml.replace('2025', year)
                    z_out.writestr(item.filename, pt_xml.encode('utf-8'))
                else:
                    z_out.writestr(item.filename, z_src.read(item.filename))

    return xlsx_response(buf.getvalue(), f'игк_{year}')