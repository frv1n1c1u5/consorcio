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

@st.cache_data
def fetch_index(series_id: str, start: str, end: str) -> pd.Series:
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados"
        f"?formato=json&dataInicial={start}&dataFinal={end}"
    )
    df = pd.DataFrame(requests.get(url).json())
    df["data"] = pd.to_datetime(df["data"], dayfirst=True)
    df["valor"] = df["valor"].str.replace(",", ".").astype(float) / 100 + 1
    df.set_index("data", inplace=True)
    return df["valor"].resample("M").prod()

# ─── Título ────────────────────────────────────────────────────────────────────
st.title("Simulador Consórcio vs Financiamento")
st.markdown(
    "Adicionamos o cálculo de CET (Custo Efetivo Total) para financiamento e consórcio."
)

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parâmetros Básicos")
    valor = st.number_input("Valor Necessário (R$)", 0.0, 1e9, 500_000.00, 1_000.00, "%.2f")
    entrada = st.number_input("Entrada (R$)",      0.0, 1e9, 100_000.00, 1_000.00, "%.2f")
    juros_ano = st.number_input("Juros Fin. (% a.a.)", 0.0, 100.0, 12.0, 0.1, "%.2f")
    prazo_fin = st.number_input("Prazo Fin. (meses)", 1, 600, 200, 1)
    modelo_fin = st.selectbox("Modelo Financiamento", ["Price", "SAC"])
    st.header("Custos Adicionais Financiamento")
    iof_pct = st.number_input("IOF (% sobre PV)",   0.0, 5.0, 0.38, 0.01, "%.2f")
    seguro_pct = st.number_input("Seguro (% a.a.)",  0.0, 10.0, 0.50, 0.01, "%.2f")
    st.header("Parâmetros Consórcio")
    prazo_cons = st.number_input("Prazo Consórcio (meses)", 1, 600, 200, 1)
    idx_choice = st.selectbox("Índice Reajuste", ["Fixo 5%", "IPCA", "INPC", "IGP-M"])
    st.header("Investimento & VPL")
    taxa_gap = st.number_input("Rendimento do Gap (% a.a.)",   0.0, 100.0, 10.0, 0.1, "%.2f")
    taxa_desc = st.number_input("Taxa Desconto p/ VPL (% a.a.)",0.0, 100.0, 10.0, 0.1, "%.2f")
    calcular = st.button("Calcular")

if not calcular:
    st.info("Preencha os parâmetros e clique em **Calcular**.")
    st.stop()

# ─── 1) Financiamento ───────────────────────────────────────────────────────────
PV = valor - entrada
r_mens = (1 + juros_ano/100)**(1/12) - 1
n_fin = int(prazo_fin)
meses_fin = np.arange(1, n_fin+1)

# parcelas
A_price = PV * r_mens / (1 - (1 + r_mens)**(-n_fin))
df_price = pd.DataFrame(index=meses_fin, columns=["Parcela"])
bal = PV
for m in meses_fin:
    j = bal * r_mens
    am = A_price - j
    bal -= am
    df_price.loc[m, "Parcela"] = A_price

amort = PV / n_fin
df_sac = pd.DataFrame(index=meses_fin, columns=["Parcela"])
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

# ─── 3) Total Pago ─────────────────────────────────────────────────────────────
total_fin = df_fin["Parcela"].sum() + entrada
total_cons= df_cons["Parcela"].sum()
df_tot = pd.DataFrame({
    "Alternativa":["Financiamento","Consórcio"],
    "Total Pago":[format_brl(total_fin), format_brl(total_cons)]
}).set_index("Alternativa")
st.subheader("Total Pago")
st.table(df_tot)

# ─── 4) Fluxo de Caixa Acumulado ────────────────────────────────────────────────
cf_fin  = [ PV ] + [-p for p in df_fin["Parcela"]]
cf_cons = [ valor ] + [-p for p in df_cons["Parcela"]]
L = max(len(cf_fin), len(cf_cons))
cf_fin  += [0]*(L-len(cf_fin))
cf_cons += [0]*(L-len(cf_cons))
df_cf = pd.DataFrame({
    "Mês": np.arange(0, L),
    "Financiamento": np.cumsum(cf_fin),
    "Consórcio":    np.cumsum(cf_cons)
})
fig_cf = px.line(df_cf, x="Mês", y=["Financiamento","Consórcio"],
                 title="Fluxo de Caixa Acumulado", template="plotly_white")
fig_cf.update_layout(yaxis_tickformat=",.0f")
st.subheader("Fluxo de Caixa Acumulado")
st.plotly_chart(fig_cf, use_container_width=True)

# ─── 5) VPL, TIR e CET ──────────────────────────────────────────────────────────
r_desc = (1+taxa_desc/100)**(1/12)-1

# VPL
npv_fin  = sum(cf_fin[t]/((1+r_desc)**t) for t in range(L))
npv_cons = sum(cf_cons[t]/((1+r_desc)**t) for t in range(L))

# TIR
irr_fin  = nf.irr(cf_fin)
irr_cons = nf.irr(cf_cons)
tir_fin  = (1+irr_fin)**12-1 if irr_fin else None
tir_cons = (1+irr_cons)**12-1 if irr_cons else None

# CET Financiamento: inclui IOF e seguro
# IOF e seguro no PV e parcelas
iof_amt = PV * iof_pct/100
pv_net = PV - iof_amt
mensal_seg = PV * (seguro_pct/100)/12
cf_cet_fin = [ pv_net ] + [ -(float(df_fin.loc[m,"Parcela"]) + mensal_seg) for m in meses_fin ]
cet_irr = nf.irr(cf_cet_fin)
cet_fin = (1+cet_irr)**12-1 if cet_irr else None

# CET Consórcio: crédito líquido após admin+reserva
pv_cons_net = valor * (1 - 0.20 - 0.03)
cf_cet_cons = [ pv_cons_net ] + [ -p for p in df_cons["Parcela"] ]
cet_irr2 = nf.irr(cf_cet_cons)
cet_cons = (1+cet_irr2)**12-1 if cet_irr2 else None

c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("VPL Fin.", format_brl(npv_fin))
c2.metric("VPL Cons.",format_brl(npv_cons))
c3.metric("TIR Fin.",  f"{tir_fin*100:.2f}%" if tir_fin else "—")
c4.metric("TIR Cons.", f"{tir_cons*100:.2f}%" if tir_cons else "—")
c5.metric("CET Fin.",  f"{cet_fin*100:.2f}%" if cet_fin else "—")
c6.metric("CET Cons.", f"{cet_cons*100:.2f}%" if cet_cons else "—")

# ─── 6) Parcelas & Alertas ─────────────────────────────────────────────────────
length = max(len(df_fin), len(df_cons))
x      = np.arange(1, length+1)
fin_p  = list(df_fin["Parcela"]) + [None]*(length-len(df_fin))
cons_p = list(df_cons["Parcela"])+ [None]*(length-len(df_cons))
gap    = np.array([(f or 0)-(c or 0) for f,c in zip(fin_p,cons_p)])
flips  = [i+1 for i in range(1,len(gap)) if np.sign(gap[i])!=np.sign(gap[i-1])]

fig = go.Figure()
fig.add_trace(go.Bar(x=x, y=cons_p, name="Consórcio",    marker_color="#00FFC2", width=0.6))
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
- **CET Financiamento**: IRR incluindo IOF no PV e seguro mensal.  
- **CET Consórcio**: IRR considerando crédito líquido (sem admin+reserva).  
- **TIR**: IRR do fluxo padrão (crédito e parcelas).  
- **VPL**: descontado à taxa informada.  
""")
