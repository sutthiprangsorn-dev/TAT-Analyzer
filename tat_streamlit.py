#!/usr/bin/env python3
"""
TAT & Workload Analyzer  -  Streamlit Web App
Deploy: https://streamlit.io/cloud
"""

import streamlit as st
import pandas as pd
import numpy as np
import io
from datetime import datetime
from statistics import mode as _stat_mode

# ---------------------------------------------------------------------------
# Constants (shared with local app)
# ---------------------------------------------------------------------------

INSTRUMENT_KEYWORDS = [
    'inst_name', 'instrument_name', 'inst_id', 'analyzer_name',
    'analyser_name', 'instrument_id', 'analyzer', 'analyser',
    'instrument', 'inst', 'machine', 'device', 'analyzed_by',
    'analysed_by', 'instrument_analyze', 'analyze_by',
]
SAMPLE_ID_KEYWORDS = [
    'bclabel', 'bc_label', 'sampleid', 'sample_id', 'orderid',
    'order_id', 'accession', 'specimen_id', 'specimenid',
    'barcode', 'labno', 'lab_no', 'caseid', 'case_id',
]
TEST_KEYWORDS = [
    'testname', 'test_name', 'testcode', 'test_code',
    'examination', 'analyte', 'panel', 'profile', 'assay',
]
DATETIME_KEYWORDS = [
    '_dt', 'datetime', '_time', 'date', 'timestamp', '_seen', 'hour', 'time',
]
RANGE_COLORS = ['#1a56db', '#059669', '#7c3aed', '#d97706', '#dc2626', '#0891b2']

SEP_MAP = {
    ', (comma)':  ',',
    '; (semicolon)': ';',
    'Tab':        '\t',
    '| (pipe)':   '|',
    '^ (caret)':  '^',
    '~ (tilde)':  '~',
    ': (colon)':  ':',
    'Space':      ' ',
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def detect_by_keywords(df, keywords):
    results = []
    for col in df.columns:
        col_lower = col.lower().replace(' ', '_')
        for kw in keywords:
            if kw.lower() in col_lower:
                if col not in results:
                    results.append(col)
                break
    return results


def detect_datetime_cols(df):
    results = []
    for col in df.columns:
        if any(kw in col.lower() for kw in DATETIME_KEYWORDS):
            results.append(col)
        elif df[col].dtype == object:
            sample = df[col].dropna().head(5)
            if len(sample):
                try:
                    pd.to_datetime(sample, dayfirst=True)
                    results.append(col)
                except Exception:
                    pass
    return results


def first_match(candidates, pool):
    for c in candidates:
        if c in pool:
            return c
    return ''


def make_range_label(from_col, to_col):
    def short(c):
        return c.replace('_DT', '').replace('_dt', '').replace('_', '').strip()
    if from_col and to_col:
        return f"{short(from_col)}-{short(to_col)}"
    return ''


def sniff_separator(raw_bytes, enc='utf-8-sig'):
    """Return the best-guess display key for the file's delimiter."""
    try:
        text  = raw_bytes.decode(enc, errors='replace')
        lines = [l for l in text.split('\n') if l.strip()][:10]
    except Exception:
        return ', (comma)'

    candidates = [
        (', (comma)',     ','),
        ('; (semicolon)', ';'),
        ('Tab',           '\t'),
        ('| (pipe)',      '|'),
        ('^ (caret)',     '^'),
        ('~ (tilde)',     '~'),
        (': (colon)',     ':'),
    ]
    best_key, best_score = ', (comma)', -1
    for disp, char in candidates:
        counts = [l.count(char) for l in lines]
        if not counts or max(counts) == 0:
            continue
        try:
            modal = _stat_mode(counts)
        except Exception:
            modal = counts[0]
        consistency = sum(1 for c in counts if c == modal) / len(counts)
        score = consistency * (modal + 1)
        if modal + 1 >= 2 and score > best_score:
            best_score, best_key = score, disp
    return best_key


def grp_stats_multi(sub, name, sid_col, pct, pct_lbl, tat_col_map):
    n_smp = sub[sid_col].nunique() if sid_col and sid_col in sub.columns else len(sub)
    n_tst = len(sub)
    row   = {'Group': name, 'Samples': n_smp, 'Tests': n_tst}
    for lbl, tat_col in tat_col_map:
        tat   = sub[tat_col].dropna()
        tat   = tat[tat >= 0]
        valid = len(tat)
        if valid == 0:
            row[f'Min ({lbl})']       = None
            row[f'Max ({lbl})']       = None
            row[f'Mean ({lbl})']      = None
            row[f'Median ({lbl})']    = None
            row[f'{pct_lbl} ({lbl})'] = None
            row[f'Quality ({lbl})']   = f"0 / {n_tst} valid"
        else:
            row[f'Min ({lbl})']       = round(float(tat.min()),             1)
            row[f'Max ({lbl})']       = round(float(tat.max()),             1)
            row[f'Mean ({lbl})']      = round(float(tat.mean()),            1)
            row[f'Median ({lbl})']    = round(float(tat.median()),          1)
            row[f'{pct_lbl} ({lbl})'] = round(float(tat.quantile(pct/100)),1)
            row[f'Quality ({lbl})']   = f"{valid:,} / {n_tst:,} valid"
    return row


# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------

def _init():
    defaults = {
        'df_raw':        None,
        'df_calc':       None,
        'result_df':     None,
        'result_rows':   None,
        'tat_col_map':   [],
        'valid_ranges':  [],
        'pct_lbl':       'P90',
        'kpi':           {},
        'calculated':    False,
        'ranges':        [{'label': 'Range 1', 'from': '', 'to': ''}],
        'dt_cols':       [],
        'auto_inst':     '',
        'auto_test':     '',
        'auto_sid':      '',
        'auto_wl':       '',
        'sniffed_sep':   ', (comma)',
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ---------------------------------------------------------------------------
# Page config & global CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TAT & Workload Analyzer",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #f3f4f6; }
.block-container { padding-top: 1rem !important; }

.app-header {
    background: linear-gradient(135deg, #1e3a8a 0%, #1a56db 100%);
    padding: 1rem 2rem 0.8rem;
    border-radius: 10px;
    margin-bottom: 1.2rem;
}
.app-header h1 { color: white; margin: 0; font-size: 1.7rem; }
.app-header p  { color: #bfdbfe; margin: 0.2rem 0 0; font-size: 0.85rem; }

.range-row {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 0.5rem 0.8rem;
    margin-bottom: 0.4rem;
}

.section-banner {
    padding: 0.45rem 1rem;
    border-radius: 6px;
    color: white;
    font-weight: 700;
    font-size: 1rem;
    margin: 1.1rem 0 0.3rem;
}

div[data-testid="metric-container"] {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0.6rem 1rem;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("""
<div class="app-header">
  <h1>🔬 TAT &amp; Workload Analyzer</h1>
  <p>Laboratory Information System — Turn Around Time &amp; Workload Analysis</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([
    "  1 ▸ Load Data  ",
    "  2 ▸ Configuration  ",
    "  3 ▸ Filters  ",
    "  4 ▸ Results  ",
])

# ===========================================================================
# TAB 1  —  Load Data
# ===========================================================================

with tab1:
    st.subheader("Data Source")

    up_col, enc_col = st.columns([3, 1])
    with up_col:
        uploaded = st.file_uploader(
            "Upload CSV / TSV file",
            type=['csv', 'tsv', 'txt'],
            help="Supported formats: .csv  .tsv  .txt",
        )
    with enc_col:
        enc = st.selectbox(
            "Encoding",
            ["utf-8-sig", "utf-8", "latin-1", "cp874", "cp1252"],
            key='enc',
        )

    # Auto-detect separator from first bytes
    if uploaded is not None:
        raw_head = uploaded.read(8192)
        uploaded.seek(0)
        st.session_state.sniffed_sep = sniff_separator(raw_head, enc)

    sep_opts       = list(SEP_MAP.keys())
    default_sep_i  = sep_opts.index(st.session_state.sniffed_sep) \
                     if st.session_state.sniffed_sep in sep_opts else 0

    sep_col, hint_col = st.columns([1, 3])
    with sep_col:
        sep_display = st.selectbox("Separator", sep_opts, index=default_sep_i, key='sep')
    with hint_col:
        if uploaded is not None:
            st.info(
                f"Auto-detected: **{st.session_state.sniffed_sep}**  "
                f"{'(matches your selection)' if sep_display == st.session_state.sniffed_sep else '— you changed it, that is fine'}"
            )

    sep_char = SEP_MAP[sep_display]

    if st.button("  ▶  Load Data", type="primary"):
        if uploaded is None:
            st.error("Please upload a file first.")
        else:
            with st.spinner("Loading file..."):
                try:
                    uploaded.seek(0)
                    df = pd.read_csv(uploaded, sep=sep_char, encoding=enc, low_memory=False)
                    st.session_state.df_raw     = df
                    st.session_state.calculated = False
                    st.session_state.result_df  = None

                    # Auto-detect columns
                    dt_cols = detect_datetime_cols(df)
                    all_cols = list(df.columns)

                    from_pick = first_match(
                        ['order_DT','order_datetime','order_date','Order_DT'], dt_cols
                    ) or (dt_cols[0] if dt_cols else '')
                    to_pick = first_match(
                        ['TechVal_DT','MedVal_DT','result_DT','instrument_result_DT'], dt_cols
                    ) or (dt_cols[-1] if len(dt_cols) > 1 else '')

                    lbl0 = make_range_label(from_pick, to_pick) or 'Range 1'
                    st.session_state.ranges = [{'label': lbl0, 'from': from_pick, 'to': to_pick}]

                    inst_c = first_match(['inst_name','instrument_name','analyzer_name'],
                                          detect_by_keywords(df, INSTRUMENT_KEYWORDS))
                    test_c = first_match(['TestName','test_name','TestCode'],
                                          detect_by_keywords(df, TEST_KEYWORDS))
                    sid_c  = first_match(['BCLabel','SampleID','OrderID','barcode'],
                                          detect_by_keywords(df, SAMPLE_ID_KEYWORDS))

                    st.session_state.dt_cols   = dt_cols
                    st.session_state.auto_inst = inst_c
                    st.session_state.auto_test = test_c
                    st.session_state.auto_sid  = sid_c
                    st.session_state.auto_wl   = from_pick

                    st.success(
                        f"Loaded **{len(df):,} rows** x **{len(df.columns)} columns**  "
                        f"— go to Tab 2 to configure"
                    )
                except Exception as exc:
                    st.error(f"Load error: {exc}")

    # File info table
    if st.session_state.df_raw is not None:
        df = st.session_state.df_raw
        st.divider()
        st.subheader("File Information")

        m1, m2, m3 = st.columns(3)
        m1.metric("Rows",    f"{len(df):,}")
        m2.metric("Columns", len(df.columns))
        m3.metric("File",    uploaded.name if uploaded else "(previously loaded)")

        info_rows = []
        for col in df.columns:
            info_rows.append({
                'Column':   col,
                'Type':     str(df[col].dtype),
                'Non-null': f"{df[col].notna().sum():,}",
                'Unique':   f"{df[col].nunique():,}",
                'Sample':   str(df[col].dropna().iloc[0]) if df[col].notna().any() else '',
            })
        st.dataframe(pd.DataFrame(info_rows), use_container_width=True, height=300, hide_index=True)


# ===========================================================================
# TAB 2  —  Configuration
# ===========================================================================

with tab2:
    if st.session_state.df_raw is None:
        st.info("Load data first (Tab 1).")
    else:
        df       = st.session_state.df_raw
        all_cols = [''] + list(df.columns)
        dt_cols  = st.session_state.dt_cols or detect_datetime_cols(df)
        dt_opts  = [''] + dt_cols

        # ── TAT Timestamp Ranges ─────────────────────────────────────────────
        st.subheader("TAT Timestamp Ranges")
        st.caption(
            "Add one row per TAT stage you want to measure simultaneously.  "
            "Each range produces its own section in the Results tab."
        )

        # Column headers
        h1, h2, h3, hx = st.columns([2, 3, 3, 0.6])
        h1.markdown("**Label**")
        h2.markdown("**FROM  (start)**")
        h3.markdown("**TO  (end)**")

        ranges     = st.session_state.ranges
        to_delete  = None

        for i, rng in enumerate(ranges):
            color = RANGE_COLORS[i % len(RANGE_COLORS)]
            with st.container():
                c1, c2, c3, c4 = st.columns([2, 3, 3, 0.6])

                with c1:
                    new_lbl = st.text_input(
                        f"lbl_{i}", value=rng['label'], key=f"lbl_{i}",
                        label_visibility='collapsed'
                    )
                    rng['label'] = new_lbl

                with c2:
                    fi = dt_opts.index(rng['from']) if rng['from'] in dt_opts else 0
                    new_from = st.selectbox(
                        f"from_{i}", options=dt_opts, index=fi,
                        key=f"from_{i}", label_visibility='collapsed'
                    )
                    if new_from != rng['from']:
                        rng['from'] = new_from
                        # Auto-label if user hasn't locked it
                        if not rng.get('locked'):
                            rng['label'] = make_range_label(new_from, rng['to']) or rng['label']

                with c3:
                    ti = dt_opts.index(rng['to']) if rng['to'] in dt_opts else 0
                    new_to = st.selectbox(
                        f"to_{i}", options=dt_opts, index=ti,
                        key=f"to_{i}", label_visibility='collapsed'
                    )
                    if new_to != rng['to']:
                        rng['to'] = new_to
                        if not rng.get('locked'):
                            rng['label'] = make_range_label(rng['from'], new_to) or rng['label']

                with c4:
                    if len(ranges) > 1 and st.button("✕", key=f"del_{i}"):
                        to_delete = i

        if to_delete is not None:
            st.session_state.ranges.pop(to_delete)
            st.rerun()

        if st.button("＋  Add Timestamp Range"):
            n = len(st.session_state.ranges) + 1
            st.session_state.ranges.append({'label': f'Range {n}', 'from': '', 'to': ''})
            st.rerun()

        st.caption(
            "💡  Auto-label updates when you pick FROM / TO.  "
            "Edit the Label field to lock your own name."
        )

        st.divider()

        # ── Column Mapping ────────────────────────────────────────────────────
        st.subheader("Column Mapping")
        cm1, cm2, cm3 = st.columns(3)

        with cm1:
            inst_i = all_cols.index(st.session_state.auto_inst) \
                     if st.session_state.auto_inst in all_cols else 0
            st.selectbox("Instrument column", all_cols, index=inst_i,
                          key='cfg_inst', help="inst_name / instrument / analyzer / machine")

        with cm2:
            test_i = all_cols.index(st.session_state.auto_test) \
                     if st.session_state.auto_test in all_cols else 0
            st.selectbox("Test name column", all_cols, index=test_i,
                          key='cfg_test', help="TestName / test_name / TestCode / examination")

        with cm3:
            sid_i = all_cols.index(st.session_state.auto_sid) \
                    if st.session_state.auto_sid in all_cols else 0
            st.selectbox("Sample ID column", all_cols, index=sid_i,
                          key='cfg_sid', help="BCLabel / SampleID / OrderID / barcode")

        st.divider()

        # ── Analysis Settings ─────────────────────────────────────────────────
        st.subheader("Analysis Settings")
        as1, as2 = st.columns(2)

        with as1:
            st.number_input("Percentile", min_value=1, max_value=99,
                             value=90, step=5, key='cfg_pct',
                             help="e.g. 90 = 90th percentile")
        with as2:
            st.radio("Group By",
                      ["Test Name", "Instrument", "Test + Instrument", "Overall"],
                      horizontal=True, key='cfg_grp')

        st.divider()

        # ── Workload Settings ─────────────────────────────────────────────────
        st.subheader("Workload Settings")
        ws1, ws2 = st.columns(2)

        with ws1:
            wl_i = dt_opts.index(st.session_state.auto_wl) \
                   if st.session_state.auto_wl in dt_opts else 0
            st.selectbox("Workload date column", dt_opts, index=wl_i,
                          key='cfg_wl',
                          help="Typically the same as the first FROM timestamp")
        with ws2:
            st.radio("Aggregate by",
                      ["Hour", "Day", "Week", "Month"],
                      horizontal=True, index=1, key='cfg_period')


# ===========================================================================
# TAB 3  —  Filters  +  Calculate
# ===========================================================================

with tab3:
    if st.session_state.df_raw is None:
        st.info("Load data first (Tab 1).")
    else:
        df       = st.session_state.df_raw
        inst_col = st.session_state.get('cfg_inst', '')
        test_col = st.session_state.get('cfg_test', '')

        st.caption(
            "Select instruments / tests to INCLUDE.  "
            "Selecting all = include everything.  "
            "Test list updates automatically when you change the Instrument selection."
        )

        fi_col, ft_col = st.columns(2)

        # Instrument filter
        with fi_col:
            all_inst = (sorted(df[inst_col].dropna().unique().astype(str))
                        if inst_col and inst_col in df.columns else [])
            sel_inst = st.multiselect(
                f"Instrument Filter  ({len(all_inst)} instruments)",
                options=all_inst, default=all_inst, key='f_inst',
            )

        # Test filter — options shrink to match selected instruments
        with ft_col:
            if inst_col and inst_col in df.columns and sel_inst \
                    and set(sel_inst) < set(all_inst):
                mask        = df[inst_col].astype(str).isin(sel_inst)
                avail_tests = (sorted(df.loc[mask, test_col].dropna().unique().astype(str))
                               if test_col and test_col in df.columns else [])
                caption = (f"Test Name Filter  ({len(avail_tests)} tests "
                           f"on selected instruments)")
            else:
                avail_tests = (sorted(df[test_col].dropna().unique().astype(str))
                               if test_col and test_col in df.columns else [])
                caption = f"Test Name Filter  ({len(avail_tests)} tests)"

            sel_test = st.multiselect(
                caption, options=avail_tests, default=avail_tests, key='f_test',
            )

        st.divider()

        # ── Calculate ─────────────────────────────────────────────────────────
        if st.button("  ▶  Calculate TAT & Workload", type="primary",
                      use_container_width=True):

            ranges = st.session_state.ranges
            valid_ranges = [
                (r['label'].strip() or f"Range {i+1}", r['from'], r['to'])
                for i, r in enumerate(ranges)
                if r['from'] and r['to']
            ]

            if not valid_ranges:
                st.error("Configure at least one FROM → TO timestamp range in Tab 2.")
                st.stop()

            pct      = int(st.session_state.get('cfg_pct', 90))
            grp_by   = st.session_state.get('cfg_grp', 'Test Name')
            ic       = inst_col
            tc       = test_col
            sc       = st.session_state.get('cfg_sid', '')

            with st.spinner("Calculating..."):
                try:
                    dfw = df.copy()

                    # Parse timestamps
                    parsed = set()
                    for _, fc, toc in valid_ranges:
                        for col in (fc, toc):
                            if col not in parsed and col in dfw.columns:
                                dfw[col] = pd.to_datetime(dfw[col], errors='coerce',
                                                           dayfirst=True)
                                parsed.add(col)

                    total = len(dfw)
                    miss_mask = pd.Series(False, index=dfw.index)
                    for _, fc, toc in valid_ranges:
                        if fc in dfw.columns and toc in dfw.columns:
                            miss_mask |= dfw[fc].isna() | dfw[toc].isna()
                    missing = int(miss_mask.sum())

                    # TAT columns
                    tat_col_map = []
                    for lbl, fc, toc in valid_ranges:
                        col = f'_TAT_{lbl}'
                        if fc in dfw.columns and toc in dfw.columns:
                            dfw[col] = (dfw[toc] - dfw[fc]).dt.total_seconds() / 60
                        else:
                            dfw[col] = np.nan
                        tat_col_map.append((lbl, col))

                    # Keep valid rows
                    valid_mask = pd.Series(False, index=dfw.index)
                    for _, c in tat_col_map:
                        valid_mask |= dfw[c].notna() & (dfw[c] >= 0)
                    dfw = dfw[valid_mask].copy()

                    # Apply filters
                    if ic and ic in dfw.columns and sel_inst \
                            and set(sel_inst) < set(all_inst):
                        dfw = dfw[dfw[ic].astype(str).isin(sel_inst)]

                    all_test_all = (sorted(df[tc].dropna().unique().astype(str))
                                    if tc and tc in df.columns else [])
                    if tc and tc in dfw.columns and sel_test \
                            and set(sel_test) < set(all_test_all):
                        dfw = dfw[dfw[tc].astype(str).isin(sel_test)]

                    # KPIs
                    n_smp  = dfw[sc].nunique() if sc and sc in dfw.columns else len(dfw)
                    n_tst  = dfw[tc].nunique() if tc and tc in dfw.columns else '—'
                    st.session_state.kpi = dict(
                        rows=total, samples=n_smp, tests=n_tst,
                        valid=len(dfw), missing=missing
                    )

                    # Group by
                    grp_map = {
                        'Test Name':         [tc] if tc and tc in dfw.columns else [],
                        'Instrument':        [ic] if ic and ic in dfw.columns else [],
                        'Test + Instrument': [c for c in [tc, ic] if c and c in dfw.columns],
                        'Overall':           [],
                    }
                    grp_cols = grp_map.get(grp_by, [])
                    pct_lbl  = f"P{pct}"

                    if not grp_cols:
                        rows = [grp_stats_multi(dfw, "Overall",
                                                 sc, pct, pct_lbl, tat_col_map)]
                    else:
                        rows = []
                        for keys, sub in dfw.groupby(grp_cols, sort=True):
                            if not isinstance(keys, tuple):
                                keys = (keys,)
                            name = "  |  ".join(str(k) for k in keys)
                            rows.append(grp_stats_multi(sub, name,
                                                          sc, pct, pct_lbl, tat_col_map))
                        first_key = f'{pct_lbl} ({tat_col_map[0][0]})'
                        rows.sort(key=lambda r: r.get(first_key) or 0, reverse=True)

                    st.session_state.result_df   = pd.DataFrame(rows)
                    st.session_state.result_rows = rows
                    st.session_state.tat_col_map = tat_col_map
                    st.session_state.valid_ranges = valid_ranges
                    st.session_state.pct_lbl     = pct_lbl
                    st.session_state.df_calc     = dfw
                    st.session_state.calculated  = True

                    st.success(
                        f"Done!  {len(rows):,} group(s)  x  "
                        f"{len(tat_col_map)} range(s)  —  see Tab 4"
                    )

                except Exception:
                    import traceback
                    st.error("Calculation error:")
                    st.code(traceback.format_exc())


# ===========================================================================
# TAB 4  —  Results  +  Export
# ===========================================================================

with tab4:
    if not st.session_state.calculated or st.session_state.result_df is None:
        st.info("Run the calculation first (Tab 3).")
    else:
        kpi         = st.session_state.kpi
        rows        = st.session_state.result_rows
        tat_col_map = st.session_state.tat_col_map
        pct_lbl     = st.session_state.pct_lbl

        # ── KPI strip ────────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Rows",         f"{kpi['rows']:,}")
        k2.metric("Unique Samples",     f"{kpi['samples']:,}")
        k3.metric("Unique Test Types",  str(kpi['tests']))
        k4.metric("Valid TAT Rows",     f"{kpi['valid']:,}")
        k5.metric("Missing Timestamps", f"{kpi['missing']:,}")

        st.divider()

        # ── Results  (one section per range) ─────────────────────────────────
        stat_display = ['Group', 'Samples', 'Tests',
                        'Min', 'Max', 'Mean', 'Median', pct_lbl, 'Quality']

        for idx, (lbl, _) in enumerate(tat_col_map):
            color = RANGE_COLORS[idx % len(RANGE_COLORS)]
            st.markdown(
                f'<div class="section-banner" '
                f'style="background:{color}">  '
                f'&#9654;&nbsp; {lbl}</div>',
                unsafe_allow_html=True,
            )

            display_rows = []
            for r in rows:
                def fv(v):
                    if v is None: return None
                    if isinstance(v, float) and np.isnan(v): return None
                    return v
                display_rows.append({
                    'Group':   r.get('Group', ''),
                    'Samples': r.get('Samples', 0),
                    'Tests':   r.get('Tests', 0),
                    'Min':     fv(r.get(f'Min ({lbl})')),
                    'Max':     fv(r.get(f'Max ({lbl})')),
                    'Mean':    fv(r.get(f'Mean ({lbl})')),
                    'Median':  fv(r.get(f'Median ({lbl})')),
                    pct_lbl:   fv(r.get(f'{pct_lbl} ({lbl})')),
                    'Quality': r.get(f'Quality ({lbl})', ''),
                })

            disp_df = pd.DataFrame(display_rows)
            st.dataframe(
                disp_df,
                use_container_width=True,
                height=min(420, max(120, len(display_rows) * 36 + 48)),
                hide_index=True,
                column_config={
                    'Samples': st.column_config.NumberColumn(format="%d"),
                    'Tests':   st.column_config.NumberColumn(format="%d"),
                    'Min':     st.column_config.NumberColumn(format="%.1f"),
                    'Max':     st.column_config.NumberColumn(format="%.1f"),
                    'Mean':    st.column_config.NumberColumn(format="%.1f"),
                    'Median':  st.column_config.NumberColumn(format="%.1f"),
                    pct_lbl:   st.column_config.NumberColumn(format="%.1f"),
                },
            )

        st.divider()

        # ── Excel Export ──────────────────────────────────────────────────────
        st.subheader("Export to Excel")

        if st.button("Generate Excel Report", type="secondary"):
            with st.spinner("Building workbook..."):
                try:
                    from openpyxl import Workbook
                    from openpyxl.styles import (Font, PatternFill, Alignment,
                                                  Border, Side)
                    from openpyxl.chart import BarChart, Reference
                    from openpyxl.utils import get_column_letter

                    result_df   = st.session_state.result_df
                    df_calc     = st.session_state.df_calc
                    df_raw      = st.session_state.df_raw
                    valid_ranges = st.session_state.valid_ranges
                    ic   = st.session_state.get('cfg_inst', '')
                    tc   = st.session_state.get('cfg_test', '')
                    sc   = st.session_state.get('cfg_sid',  '')
                    wl_c = st.session_state.get('cfg_wl',   '')
                    per  = st.session_state.get('cfg_period', 'Day').lower()
                    pct  = int(pct_lbl[1:])

                    wb = Workbook()

                    hdr_fill = PatternFill("solid", fgColor="1E3A8A")
                    alt_fill = PatternFill("solid", fgColor="EFF6FF")
                    hdr_font = Font(color="FFFFFF", bold=True, name="Calibri", size=11)
                    ctr  = Alignment(horizontal='center', vertical='center',
                                      wrap_text=True)
                    thin = Border(
                        left=Side(style='thin', color='D1D5DB'),
                        right=Side(style='thin', color='D1D5DB'),
                        top=Side(style='thin', color='D1D5DB'),
                        bottom=Side(style='thin', color='D1D5DB'),
                    )

                    def hc(ws, r, c, v):
                        cell = ws.cell(row=r, column=c, value=v)
                        cell.fill, cell.font = hdr_fill, hdr_font
                        cell.alignment, cell.border = ctr, thin
                    def dc(ws, r, c, v, alt=False):
                        cell = ws.cell(row=r, column=c, value=v)
                        cell.alignment, cell.border = ctr, thin
                        if alt: cell.fill = alt_fill
                    def aw(ws, extra=4, cap=50):
                        for col in ws.columns:
                            w = max((len(str(ce.value or '')) for ce in col), default=8)
                            ws.column_dimensions[
                                get_column_letter(col[0].column)
                            ].width = min(w + extra, cap)

                    # Sheet 1 - TAT Summary
                    ws1 = wb.active
                    ws1.title = "TAT Summary"

                    rng_summary = "; ".join(
                        f"{lbl} ({fc} to {toc})"
                        for lbl, fc, toc in valid_ranges
                    )
                    meta = [
                        ("Generated",         datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                        ("TAT Ranges",         rng_summary),
                        ("Percentile",         f"{pct}th"),
                        ("Group By",           st.session_state.get('cfg_grp', '')),
                        ("Total Records",      f"{kpi['rows']:,}"),
                        ("Unique Samples",     f"{kpi['samples']:,}"),
                        ("Valid TAT Rows",     f"{kpi['valid']:,}"),
                        ("Missing Timestamps", f"{kpi['missing']:,}"),
                    ]
                    nc = max(len(result_df.columns), 2)
                    ws1.merge_cells(f'A1:{get_column_letter(nc)}1')
                    ws1['A1'] = "TAT Analysis Report"
                    ws1['A1'].font      = Font(bold=True, size=16, color="1E3A8A", name="Calibri")
                    ws1['A1'].alignment = ctr
                    ws1['A1'].fill      = alt_fill

                    for ri, (k, v) in enumerate(meta, 3):
                        ws1.cell(row=ri, column=1, value=k).font = Font(bold=True, name="Calibri")
                        ws1.cell(row=ri, column=2, value=v)

                    TBL = len(meta) + 4
                    ws1.freeze_panes = f'A{TBL+1}'
                    res_cols = list(result_df.columns)
                    for ci, cn in enumerate(res_cols, 1):
                        hc(ws1, TBL, ci, cn)
                    for ri2, (_, row) in enumerate(result_df.iterrows(), 1):
                        for ci, cn in enumerate(res_cols, 1):
                            v = row[cn]
                            if isinstance(v, float) and np.isnan(v): v = None
                            dc(ws1, TBL+ri2, ci, v, alt=(ri2 % 2 == 0))
                    aw(ws1)

                    # Sheet 2 - TAT Chart
                    ws2 = wb.create_sheet("TAT Chart")
                    chart_cols = ['Group'] + [f'{pct_lbl} ({lbl})' for lbl, _ in tat_col_map]
                    for ci, cn in enumerate(chart_cols, 1):
                        hc(ws2, 1, ci, cn)
                    n_grp = len(result_df)
                    for ri2, (_, row) in enumerate(result_df.iterrows(), 2):
                        ws2.cell(row=ri2, column=1, value=str(row.get('Group', '')))
                        for ci, (lbl, _) in enumerate(tat_col_map, 2):
                            v = row.get(f'{pct_lbl} ({lbl})')
                            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                                ws2.cell(row=ri2, column=ci, value=round(v, 1))
                    chart = BarChart()
                    chart.type = "bar"
                    chart.title = f"{pct_lbl} TAT by Group"
                    chart.y_axis.title = "Minutes"
                    chart.style = 10; chart.width = 32; chart.height = 20
                    chart.add_data(Reference(ws2, min_col=2, min_row=1,
                                              max_col=len(tat_col_map)+1, max_row=n_grp+1),
                                   titles_from_data=True)
                    chart.set_categories(Reference(ws2, min_col=1, min_row=2, max_row=n_grp+1))
                    ws2.add_chart(chart, f"{get_column_letter(len(chart_cols)+2)}2")
                    aw(ws2)

                    # Sheet 3 - Workload
                    ws3 = wb.create_sheet("Workload")
                    if wl_c and wl_c in df_raw.columns:
                        df_wl = df_raw.copy()
                        df_wl[wl_c] = pd.to_datetime(df_wl[wl_c], errors='coerce', dayfirst=True)
                        df_wl = df_wl.dropna(subset=[wl_c])
                        fmt_map = {'hour': '%Y-%m-%d %H:00', 'day': '%Y-%m-%d', 'month': '%Y-%m'}
                        if per == 'week':
                            df_wl['_period'] = df_wl[wl_c].dt.to_period('W').astype(str)
                        else:
                            df_wl['_period'] = df_wl[wl_c].dt.strftime(fmt_map.get(per, '%Y-%m-%d'))
                        wl_agg = (df_wl.groupby('_period')
                                   .agg(Total_Tests=('_period', 'count'))
                                   .reset_index()
                                   .rename(columns={'_period': 'Period', 'Total_Tests': 'Total Tests'}))
                        if sc and sc in df_wl.columns:
                            tmp = (df_wl.groupby('_period')[sc].nunique().reset_index()
                                    .rename(columns={'_period': 'Period', sc: 'Unique Samples'}))
                            wl_agg = wl_agg.merge(tmp, on='Period', how='left')
                        if tc and tc in df_wl.columns:
                            tmp = (df_wl.groupby('_period')[tc].nunique().reset_index()
                                    .rename(columns={'_period': 'Period', tc: 'Unique Test Types'}))
                            wl_agg = wl_agg.merge(tmp, on='Period', how='left')

                        wl_cols = list(wl_agg.columns)
                        for ci, cn in enumerate(wl_cols, 1): hc(ws3, 1, ci, cn)
                        for ri2, (_, row) in enumerate(wl_agg.iterrows(), 2):
                            for ci, cn in enumerate(wl_cols, 1):
                                v = row[cn]
                                if isinstance(v, float) and np.isnan(v): v = None
                                dc(ws3, ri2, ci, v, alt=(ri2 % 2 == 0))
                        if len(wl_agg):
                            wc = BarChart()
                            wc.type="col"; wc.title=f"Workload by {per.title()}"
                            wc.y_axis.title="Count"; wc.style=11
                            wc.width=28; wc.height=15
                            n_wl = len(wl_agg)
                            wc.add_data(Reference(ws3, min_col=2, min_row=1,
                                                   max_col=2, max_row=n_wl+1),
                                        titles_from_data=True)
                            wc.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=n_wl+1))
                            ws3.add_chart(wc, f"{get_column_letter(len(wl_cols)+2)}2")
                        aw(ws3)
                    else:
                        ws3['A1'] = "Workload date column not configured"

                    # Sheet 4 - Raw Data
                    ws4 = wb.create_sheet("Raw Data")
                    ws4.freeze_panes = 'A2'
                    raw = df_calc.copy()
                    rename_map = {c: f"TAT_{lbl}_min" for lbl, c in tat_col_map}
                    raw.rename(columns=rename_map, inplace=True)
                    for col in raw.columns:
                        if pd.api.types.is_datetime64_any_dtype(raw[col]):
                            raw[col] = raw[col].dt.strftime('%Y-%m-%d %H:%M:%S')
                    raw_cols = list(raw.columns)
                    for ci, cn in enumerate(raw_cols, 1): hc(ws4, 1, ci, cn)
                    MAX_R = 100_000
                    n_exp = min(len(raw), MAX_R)
                    for ri2 in range(n_exp):
                        alt = (ri2 % 2 == 0)
                        for ci, cn in enumerate(raw_cols, 1):
                            v = raw.iloc[ri2][cn]
                            if not isinstance(v, str) and pd.isna(v): v = None
                            dc(ws4, ri2+2, ci, v, alt=alt)
                    if len(raw) > MAX_R:
                        ws4.cell(row=n_exp+3, column=1,
                                  value=f"Truncated: {len(raw)-MAX_R:,} more rows not shown"
                                 ).font = Font(color="DC2626", italic=True)
                    aw(ws4, extra=2, cap=40)

                    # Save to buffer
                    buf = io.BytesIO()
                    wb.save(buf)
                    buf.seek(0)

                    fname = f"TAT_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    st.download_button(
                        label="Download Excel Report",
                        data=buf,
                        file_name=fname,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                        use_container_width=True,
                    )

                except Exception:
                    import traceback
                    st.error("Export error:")
                    st.code(traceback.format_exc())
