import streamlit as st
import pandas as pd
import numpy as np
import requests
import numpy_financial as nf
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# ─── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="Simulador Consórcio vs Financiamento")

def format_brl(x: float) -> str:
    s = f"{x:,.2f}".replace(",", "v").replace(".", ",").replace("v", ".")
    return f"R$ {s}"

@st.cache_data(show_spinner=False)
def fetch_index(series_id: str, start: str, end: str) -> pd.Series:
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados"
        f"?formato=json&dataInicial={start}&dataFinal={end}"
    )
    resp = requests.get(url)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    df["data"] = pd.to_datetime(df["data"], dayfirst=True)
    df["valor"] = df["valor"].str.replace(",", ".").astype(float) / 100 + 1
    df.set_index("data", inplace=True)
    return df["valor"].resample("M").prod()

# ─── Título ────────────────────────────────────────────────────────────────────
st.title("Simulador Consórcio vs Financiamento")
st.markdown(
    "Compare o consórcio com Price/SAC, veja fluxo de caixa, VPL/TIR, "
    "e use índices reais (IPCA, INPC, IGP-M) no reajuste."
)

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parâmetros de Entrada")
    valor = st.number_input("Valor Necessário (R$)", 0.0, 1e9, 500_000.00, 1_000.00, "%.2f")
    entrada = st.number_input("Entrada (R$)", 0.0, 1e9, 100_000.00, 1_000.00, "%.2f")
    juros_ano = st.number_input("Juros Financiamento (% a.a.)", 0.0, 100.0, 12.0, 0.1, "%.2f")
    prazo_fin = st.number_input("Prazo Financiamento (meses)", 1, 600, 200, 1)
    modelo_fin = st.selectbox("Modelo de Financiamento", ["Price", "SAC"])
    prazo_cons = st.number_input("Prazo Consórcio (meses)", 1, 600, 200, 1)
    idx_choice = st.selectbox("Índice de Reajuste do Consórcio", ["Fixo 5%", "IPCA", "INPC", "IGP-M"])
    taxa_gap = st.number_input("Rendimento do Gap (% a.a.)", 0.0, 100.0, 10.0, 0.1, "%.2f")
    taxa_desc = st.number_input("Taxa Desconto p/ VPL (% a.a.)", 0.0, 100.0, 10.0, 0.1, "%.2f")
    calcular = st.button("Calcular")

if not calcular:
    st.info("Ajuste os parâmetros e clique em **Calcular**.")
    st.stop()

# ─── 1) Financiamento ───────────────────────────────────────────────────────────
PV = valor - entrada
r_mens = (1 + juros_ano/100)**(1/12) - 1
n_fin = int(prazo_fin)
meses_fin = np.arange(1, n_fin+1)

# Price
A_price = PV * r_mens / (1 - (1 + r_mens)**(-n_fin))
df_price = pd.DataFrame(index=meses_fin, columns=["Parcela"], dtype=float)
bal = PV
for m in meses_fin:
    j = bal * r_mens
    am = A_price - j
    bal -= am
    df_price.loc[m, "Parcela"] = A_price

# SAC
amort = PV / n_fin
df_sac = pd.DataFrame(index=meses_fin, columns=["Parcela"], dtype=float)
bal = PV
for m in meses_fin:
    j = bal * r_mens
    pmt = amort + j
    bal -= amort
    df_sac.loc[m, "Parcela"] = pmt

df_fin = df_price if modelo_fin=="Price" else df_sac

# ─── 2) Consórcio ──────────────────────────────────────────────────────────────
base_cons = valor * 1.23 / prazo_cons

if idx_choice=="Fixo 5%":
    fator_anual = 1.05
    st.metric("Reajuste Anual (Fixo)", "5,00%")
else:
    series_map = {"IPCA":"433","INPC":"188","IGP-M":"189"}
    end = datetime.today().strftime("%d/%m/%Y")
    start = (datetime.today() - timedelta(days=400)).strftime("%d/%m/%Y")
    idx_series = fetch_index(series_map[idx_choice], start, end)
    last12 = idx_series[-12:]
    fator_anual = last12.prod()
    st.metric(f"Acumulado 12m ({idx_choice})", f"{(fator_anual-1)*100:.2f}%")

factors = [fator_anual ** ((m-1)//12) for m in range(1, prazo_cons+1)]
parc_cons = [base_cons * f for f in factors]
df_cons = pd.DataFrame({"Parcela":parc_cons}, index=np.arange(1, prazo_cons+1))

# ─── 3) Total Pago ──────────────────────────────────────────────────────────────
total_fin = df_fin["Parcela"].sum() + entrada
total_cons= df_cons["Parcela"].sum()
df_tot = pd.DataFrame({
    "Alternativa":["Financiamento","Consórcio"],
    "Total Pago":[format_brl(total_fin), format_brl(total_cons)]
}).set_index("Alternativa")
st.subheader("Total Pago")
st.table(df_tot)

# ─── 4) Fluxo de Caixa Acumulado ────────────────────────────────────────────────
cf_fin  = [-entrada] + (-df_fin["Parcela"]).tolist()
cf_cons = [0] + (-df_cons["Parcela"]).tolist()
L = max(len(cf_fin), len(cf_cons))
cf_fin  += [0]*(L-len(cf_fin))
cf_cons += [0]*(L-len(cf_cons))
cum_fin  = np.cumsum(cf_fin)
cum_cons = np.cumsum(cf_cons)
df_cf = pd.DataFrame({
    "Mês": np.arange(0, L),
    "Financiamento": cum_fin,
    "Consórcio":    cum_cons
})
fig_cf = px.line(df_cf, x="Mês", y=["Financiamento","Consórcio"],
                 title="Fluxo de Caixa Acumulado", template="plotly_white")
fig_cf.update_layout(yaxis_tickformat=",.0f")
st.subheader("Fluxo de Caixa Acumulado")
st.plotly_chart(fig_cf, use_container_width=True)

# ─── 5) VPL e TIR ───────────────────────────────────────────────────────────────
r_desc = (1+taxa_desc/100)**(1/12)-1
npv_fin  = sum(cf_fin[t]/((1+r_desc)**t) for t in range(L))
npv_cons = sum(cf_cons[t]/((1+r_desc)**t) for t in range(L))
irr_fin  = nf.irr(cf_fin)
irr_cons = nf.irr(cf_cons)
tir_fin  = (1+irr_fin)**12-1 if irr_fin is not None else None
tir_cons = (1+irr_cons)**12-1 if irr_cons is not None else None

c1,c2,c3,c4 = st.columns(4)
c1.metric("VPL Financiamento", format_brl(npv_fin))
c2.metric("VPL Consórcio",      format_brl(npv_cons))
c3.metric("TIR Financiamento",  f"{tir_fin*100:.2f}%" if tir_fin else "—")
c4.metric("TIR Consórcio",       f"{tir_cons*100:.2f}%" if tir_cons else "—")

# ─── 6) Parcelas & Alertas ─────────────────────────────────────────────────────
length = max(len(df_fin), len(df_cons))
x      = np.arange(1, length+1)
fin_p  = list(df_fin["Parcela"]) + [None]*(length-len(df_fin))
cons_p = list(df_cons["Parcela"])+ [None]*(length-len(df_cons))
gap    = np.array([ (f or 0)-(c or 0) for f,c in zip(fin_p,cons_p) ])
flips  = [i+1 for i in range(1,len(gap)) if np.sign(gap[i])!=np.sign(gap[i-1])]

fig = go.Figure()
fig.add_trace(go.Bar(x=x, y=cons_p, name="Consórcio",   marker_color="#00FFC2", width=0.6))
fig.add_trace(go.Bar(x=x, y=fin_p,   name="Financiamento",marker_color="#2081E2", width=0.6))
for m in flips:
    fig.add_vline(x=m, line_dash="dash", line_color="yellow",
                  annotation_text=f"Mês {m}", annotation_position="top right")
fig.update_layout(template="plotly_dark", barmode="overlay", bargap=0.15,
                  title="Parcelas & Alertas")
st.subheader("Parcelas & Alertas")
st.plotly_chart(fig, use_container_width=True)

# ─── 7) Metodologia ────────────────────────────────────────────────────────────
with st.expander("📌 Metodologia"):
    st.markdown("""
- **Fluxo de Caixa**: saldo acumulado de entrada e parcelas.  
- **VPL**: descontado à taxa informada.  
- **TIR**: anualizada via `numpy_financial.irr`.  
- **Reajuste**: fixo ou real (IPCA/INPC/IGP-M) pelos últimos 12m.  
- **Alertas**: marca meses em que o gap muda de sinal.
""")
