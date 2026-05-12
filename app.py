import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from collections import defaultdict, deque
import time
import io
import pyvista as pv
import tempfile
import os
import streamlit.components.v1 as components

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE PÁGINA Y TEMA CLARO
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="MB Production Planner PRO",
    page_icon="⛏️",
    layout="wide",
)

st.markdown("""
<style>
    :root {
        --primary-color: #1a6b9a;
        --accent-color: #e67e22;
        --bg-light: #f8f9fa;
    }
    .main { background-color: #ffffff; }
    .stMetric {
        background-color: var(--bg-light);
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 10px;
    }
    h1, h2, h3 { color: #2c3e50; }
    /* Botón principal */
    .stButton>button {
        background: linear-gradient(135deg, #1a6b9a, #14547a);
        color: white;
        border: none;
        padding: 0.75rem;
        font-weight: bold;
    }
    hr { border-top: 1px solid #d1d8e0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# FUNCIONES LÓGICAS (CORE)
# ─────────────────────────────────────────────
def compute_cutoff(C_MINING, C_PLANT, LBS_PER_TON, PRICE_CU, SMELT_DISC, RECUP):
    return ((C_MINING + C_PLANT) / (LBS_PER_TON * (PRICE_CU - SMELT_DISC) * RECUP)) * 100.0

def run_optimizer(df, H, LAG_FASE, PRICE_CU, SMELT_DISC, C_MINING, C_PLANT,
                  RATE, RECUP, CAP_ORE_T, CAP_WASTE_T, CAP_PLANT_T, LBS_PER_TON, TOL_CAP):

    ORE_CAP_EFFECTIVE = min(CAP_ORE_T, CAP_PLANT_T)
    CUT_ECON = compute_cutoff(C_MINING, C_PLANT, LBS_PER_TON, PRICE_CU, SMELT_DISC, RECUP)

    df = df.copy()
    df["fase"] = df["fase"].astype(int)
    phases = sorted(df["fase"].unique())
    df["bin"] = np.where(df["Ley"] >= CUT_ECON, 1, -1)
    df["metal"] = df["tonelaje"] * (df["Ley"] / 100.0)

    disc_factor = np.array([1.0 / ((1.0 + RATE) ** t) for t in range(H)])

    clusters_df = df.groupby(["fase", "Z"], as_index=False).agg(
        tonmineral = ("tonelaje", lambda x: x[df.loc[x.index, "bin"] == 1].sum()),
        tonesteril = ("tonelaje", lambda x: x[df.loc[x.index, "bin"] == -1].sum()),
        metal = ("metal", lambda x: x[df.loc[x.index, "bin"] == 1].sum()),
        tonelaje_total = ("tonelaje", "sum")
    )
    clusters_df["ley_%"] = (clusters_df["metal"] / clusters_df["tonmineral"].replace(0, np.nan)).fillna(0) * 100
    clusters_df = clusters_df.sort_values(["fase", "Z"], ascending=[True, False]).reset_index(drop=True)
    nU = len(clusters_df)

    cluster_index = {(int(r.fase), r.Z): idx for idx, r in clusters_df.iterrows()}
    benches_por_fase = {f: sorted(clusters_df[clusters_df["fase"] == f]["Z"].unique(), reverse=True) for f in phases}

    precedencia_vertical = defaultdict(list)
    for f in phases:
        benches = benches_por_fase[f]
        for i in range(1, len(benches)):
            u_abajo, u_arriba = cluster_index[(f, benches[i])], cluster_index[(f, benches[i - 1])]
            precedencia_vertical[u_abajo].append(u_arriba)

    mined_period, mined_mask = np.zeros(nU, dtype=int), np.zeros(nU, dtype=bool)
    fase_start_period, fase_deepest_bench_idx = {p: -1 for p in phases}, {p: -1 for p in phases}
    res_rows, total_van = [], 0.0
    valor_por_ton_metal = (PRICE_CU - SMELT_DISC) * LBS_PER_TON * RECUP

    progress_bar = st.progress(0, text="Calculando plan...")

    for t in range(1, H + 1):
        progress_bar.progress(t / H)
        if t == 1:
            fase_start_period[phases[0]], active_phases = t, [phases[0]]
        else:
            active_phases = [p for p in phases if fase_start_period[p] != -1]
            for p_idx in range(1, len(phases)):
                p, p_prev = phases[p_idx], phases[p_idx - 1]
                if fase_start_period[p] == -1 and fase_start_period[p_prev] != -1:
                    if fase_deepest_bench_idx[p_prev] >= (LAG_FASE - 1):
                        fase_start_period[p] = t
                        active_phases.append(p)

        ore_mined = waste_mined = metal_mined = 0.0
        ore_rem, waste_rem, move_rem = ORE_CAP_EFFECTIVE, CAP_WASTE_T, ORE_CAP_EFFECTIVE + CAP_WASTE_T
        rr_queue = deque(active_phases)

        while rr_queue and move_rem > TOL_CAP:
            f = rr_queue.popleft()
            for z in benches_por_fase[f]:
                u = cluster_index[(f, z)]
                if mined_mask[u] or any(not mined_mask[up] for up in precedencia_vertical[u]): continue

                t_tot, t_ore, t_waste, m_u = clusters_df.loc[u, ["tonelaje_total", "tonmineral", "tonesteril", "metal"]]
                if move_rem - t_tot < -TOL_CAP or ore_rem - t_ore < -TOL_CAP or waste_rem - t_waste < -TOL_CAP: break

                mined_period[u], mined_mask[u] = t, True
                ore_mined, waste_mined, metal_mined = ore_mined + t_ore, waste_mined + t_waste, metal_mined + m_u
                ore_rem, waste_rem, move_rem = ore_rem - t_ore, waste_rem - t_waste, move_rem - t_tot
                fase_deepest_bench_idx[f] = max(fase_deepest_bench_idx[f], benches_por_fase[f].index(z))
                rr_queue.append(f)
                break

        ley_mina = (metal_mined / ore_mined * 100) if ore_mined > 0 else 0
        van_t = ((valor_por_ton_metal * metal_mined) - (C_MINING * (ore_mined + waste_mined) + C_PLANT * ore_mined)) * disc_factor[t-1]
        total_van += van_t
        res_rows.append({"periodo": t, "mineral_Mt": ore_mined/1e6, "esteril_Mt": waste_mined/1e6, 
                         "mov_total_Mt": (ore_mined+waste_mined)/1e6, "ley_mina_pct": ley_mina, "VAN_MUSD": van_t/1e6})

    res_df = pd.DataFrame(res_rows)
    res_df["VAN_acum_MUSD"] = res_df["VAN_MUSD"].cumsum()
    dict_periodo = {(int(clusters_df.loc[i, "fase"]), clusters_df.loc[i, "Z"]): int(mined_period[i]) for i in range(nU)}
    df["periodo"] = df.apply(lambda r: dict_periodo.get((int(r["fase"]), r["Z"]), 0), axis=1)
    return res_df, clusters_df, df, total_van, CUT_ECON

# ─────────────────────────────────────────────
# FUNCIONES VISUALES (TEMA CLARO)
# ─────────────────────────────────────────────
def make_fig_movement(res_df):
    plt.style.use('default')
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.set_facecolor('#ffffff')
    fig.patch.set_facecolor('#ffffff')

    years = res_df["periodo"]
    
    # Mineral y Esteril apilados
    ax1.bar(years, res_df["mineral_Mt"], color='#ef8114', label="Mineral (Mt)")
    ax1.bar(years, res_df["esteril_Mt"], bottom=res_df["mineral_Mt"], color='#a6a6a6', label="Estéril (Mt)")
    
    ax1.set_xlabel("Periodo", fontsize=10, fontweight='bold')
    ax1.set_ylabel("Movimiento (Mt)", fontsize=10, fontweight='bold')
    ax1.grid(axis='y', linestyle='-', alpha=0.3)
    ax1.set_xticks(years)
    
    ax2 = ax1.twinx()
    ax2.plot(years, res_df["ley_mina_pct"], color='#00a650', linewidth=3, marker='o', label="Ley Cu (%)")
    ax2.set_ylabel("Ley Cu (%)", fontsize=10, fontweight='bold', color='#00a650')
    
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=3, frameon=False)
    
    fig.tight_layout()
    return fig

def make_fig_van(res_df):
    plt.style.use('default')
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.set_facecolor('#ffffff')
    fig.patch.set_facecolor('#ffffff')

    years = res_df["periodo"]
    
    ax1.bar(years, res_df["VAN_MUSD"], color='#1a6b9a', label="VAN Periodo (MUSD)")
    ax1.set_xlabel("Periodo", fontsize=10, fontweight='bold')
    ax1.set_ylabel("VAN (MUSD)", fontsize=10, fontweight='bold')
    ax1.grid(axis='y', linestyle='-', alpha=0.3)
    ax1.set_xticks(years)
    
    ax2 = ax1.twinx()
    ax2.plot(years, res_df["VAN_acum_MUSD"], color='#ef8114', linewidth=3, marker='s', label="VAN Acumulado (MUSD)")
    ax2.set_ylabel("VAN Acumulado (MUSD)", fontsize=10, fontweight='bold', color='#ef8114')
    
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=2, frameon=False)
    
    fig.tight_layout()
    return fig

def render_3d_viewer(df, current_periodo, dx=15.0, dy=15.0, dz=15.0):
    # Mostrar bloques que se minarán en el futuro (periodo > actual) para ver cómo "desaparecen"
    df_plot = df[(df["periodo"] > current_periodo) & (df["periodo"] > 0)].copy()
    if df_plot.empty: return None
    
    # Reducción de datos para fluidez si es muy grande
    if len(df_plot) > 50000:
        df_plot = df_plot.sample(50000)

    points = df_plot[["X", "Y", "Z"]].values
    cloud = pv.PolyData(points)
    cloud["Periodo"] = df_plot["periodo"].values
    
    # Geometría de bloque
    geom = pv.Cube(x_length=dx, y_length=dy, z_length=dz)
    glyphs = cloud.glyph(geom=geom, scale=False)
    
    plotter = pv.Plotter(window_size=[700, 500])
    # Título se remueve de add_mesh para evitar TypeError
    plotter.add_mesh(glyphs, scalars="Periodo", cmap="turbo", show_scalar_bar=True)
    plotter.add_text("Secuencia de Minado", font_size=12, color="black")
    plotter.set_background("white")
    plotter.view_isometric()
    return plotter

# ─────────────────────────────────────────────
# INTERFAZ STREAMLIT
# ─────────────────────────────────────────────
st.title("⛏️ MB Production Planner PRO")
st.markdown("---")

with st.sidebar:
    st.header("📂 Configuración")
    uploaded_file = st.file_uploader("Modelo de Bloques (CSV)", type=["csv"])
    
    col_x, col_y, col_z = "X", "Y", "Z"
    col_fase, col_ley, col_ton = "fase", "Ley", "tonelaje"
    dx, dy, dz = 15.0, 15.0, 15.0
    
    if uploaded_file is not None:
        # Leer solo encabezados para mapeo
        df_preview = pd.read_csv(uploaded_file, nrows=0)
        cols = df_preview.columns.tolist()
        
        st.subheader("🔗 Mapeo de Columnas")
        col_x = st.selectbox("Columna X", cols, index=cols.index("X") if "X" in cols else 0)
        col_y = st.selectbox("Columna Y", cols, index=cols.index("Y") if "Y" in cols else 0)
        col_z = st.selectbox("Columna Z", cols, index=cols.index("Z") if "Z" in cols else 0)
        col_fase = st.selectbox("Columna Fase", cols, index=cols.index("fase") if "fase" in cols else 0)
        col_ley = st.selectbox("Columna Ley", cols, index=cols.index("Ley") if "Ley" in cols else 0)
        col_ton = st.selectbox("Columna Tonelaje", cols, index=cols.index("tonelaje") if "tonelaje" in cols else 0)
        
        st.subheader("🧊 Dimensiones de Bloque")
        col1, col2, col3 = st.columns(3)
        dx = col1.number_input("DX", value=15.0)
        dy = col2.number_input("DY", value=15.0)
        dz = col3.number_input("DZ", value=15.0)

    st.subheader("⚙️ Parámetros")
    H = st.slider("Periodos", 5, 40, 20)
    LAG_FASE = st.slider("Lag (Bancos)", 1, 8, 3)
    
    st.subheader("💰 Económicos")
    PRICE_CU = st.number_input("Precio Cu (USD/lb)", 4.0)
    C_MINING = st.number_input("Costo Mina (USD/t)", 2.5)
    C_PLANT = st.number_input("Costo Planta (USD/t)", 12.0)
    CAP_PLANT_T = st.number_input("Cap. Planta (t/per)", 30_000_000)
    
    run_btn = st.button("EJECUTAR PLANIFICACIÓN")

if "optimizer_run" not in st.session_state:
    st.session_state.optimizer_run = False

if run_btn and uploaded_file:
    uploaded_file.seek(0)
    df_raw = pd.read_csv(uploaded_file)
    
    # Renombrar columnas a los nombres internos esperados
    df_raw = df_raw.rename(columns={
        col_x: "X", col_y: "Y", col_z: "Z",
        col_fase: "fase", col_ley: "Ley", col_ton: "tonelaje"
    })
    
    t0 = time.time()
    
    res_df, cl_df, df_out, van_tot, cut_e = run_optimizer(
        df_raw, H, LAG_FASE, PRICE_CU, 0.1, C_MINING, C_PLANT, 0.1, 0.9, 
        40e6, 70e6, CAP_PLANT_T, 2204.6, 1.0
    )
    
    st.session_state.res_df = res_df
    st.session_state.df_out = df_out
    st.session_state.van_tot = van_tot
    st.session_state.cut_e = cut_e
    st.session_state.elapsed = time.time() - t0
    st.session_state.dx = dx
    st.session_state.dy = dy
    st.session_state.dz = dz
    st.session_state.optimizer_run = True

if st.session_state.optimizer_run:
    res_df = st.session_state.res_df
    df_out = st.session_state.df_out
    van_tot = st.session_state.van_tot
    cut_e = st.session_state.cut_e
    elapsed = st.session_state.elapsed

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("VAN TOTAL", f"${van_tot/1e6:,.1f} MUSD")
    c2.metric("LEY CORTE", f"{cut_e:.3f} %")
    c3.metric("MINERAL", f"{res_df['mineral_Mt'].sum():,.1f} Mt")
    c4.metric("TIEMPO", f"{elapsed:.1f} s")

    # Visualización
    tab1, tab2, tab3 = st.tabs(["🚀 Visor 3D Interactivo", "📈 Gráficos de Reporte", "📋 Tablas"])
    
    with tab1:
        st.subheader("Secuencia de Minado Espacial (Extracción)")
        max_p = int(df_out["periodo"].max())
        if max_p > 0:
            col1, col2 = st.columns([3, 1])
            with col1:
                visor_periodo = st.slider("Minado hasta el periodo (Se ocultan bloques ya comidos):", 0, max_p, 0)
            with col2:
                st.write("") # Spacer
                play_btn = st.button("▶️ Reproducir Video Animado")
                
            view_container = st.empty()
            
            def draw_scene(per):
                plotter = render_3d_viewer(df_out, current_periodo=per, 
                                           dx=st.session_state.dx, 
                                           dy=st.session_state.dy, 
                                           dz=st.session_state.dz)
                if plotter: 
                    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
                        plotter.export_html(f.name)
                        with open(f.name, "r", encoding="utf-8") as html_file:
                            html_str = html_file.read()
                    try: os.unlink(f.name)
                    except: pass
                    with view_container:
                        components.html(html_str, height=550)
                else: 
                    with view_container:
                        st.info("La mina se ha agotado. Todos los bloques han sido minados en este periodo.")

            if play_btn:
                for p in range(0, max_p + 1):
                    draw_scene(p)
                    time.sleep(0.5)
            else:
                draw_scene(visor_periodo)
        else:
            st.warning("No se minaron bloques.")
        
    with tab2:
        st.pyplot(make_fig_movement(res_df), use_container_width=True)
        st.pyplot(make_fig_van(res_df), use_container_width=True)
        
    with tab3:
        st.dataframe(res_df.style.background_gradient(subset=['VAN_MUSD'], cmap='YlGn'))

elif not uploaded_file:
    st.info("Carga un CSV con columnas: X, Y, Z, fase, Ley, tonelaje")