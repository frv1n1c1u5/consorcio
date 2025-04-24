import streamlit as st
import pandas as pd
import numpy as np
import requests
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
    """Busca índice mensal (1 + variação) do SGS/BCB para série dada."""
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados"
        f"?formato=json&dataInicial={start}&dataFinal={end}"
    )
    r = requests.get(url)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df['data'] = pd.to_datetime(df['data'], dayfirst=True)
    df['valor'] = df['valor'].str.replace(',', '.').astype(float)/100 + 1
    df.set_index('data', inplace=True)
    # mês de referência: usar fim de mês
    return df['valor'].resample('M').prod()

# ─── Título ────────────────────────────────────────────────────────────────────
st.title("Simulador Consórcio vs Financiamento")
st.markdown(
    "Compare o consórcio com Price/SAC, veja fluxo de caixa acumulado, VPL/TIR, "
    "e ajuste por índices (IPCA, INPC, IGP-M)."
)

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parâmetros de Entrada")
    valor = st.number_input("Valor Necessário (R$)", min_value=0.0, value=500_000.00, step=1_000.00, format="%.2f")
    entrada = st.number_input("Entrada (R$)", min_value=0.0, value=100_000.00, step=1_000.00, format="%.2f")
    juros_ano = st.number_input("Juros Financiamento (% a.a.)", min_value=0.0, value=12.0, step=0.1, format="%.2f")
    prazo_fin = st.number_input("Prazo Financiamento (meses)", min_value=1, value=200, step=1)
    modelo_fin = st.selectbox("Modelo de Financiamento", ["Price", "SAC"])
    prazo_cons = st.number_input("Prazo Consórcio (meses)", min_value=1, value=200, step=1)
    idx_choice = st.selectbox("Índice de Reajuste do Consórcio", ["Fixo 5%", "IPCA", "INPC", "IGP-M"])
    taxa_gap = st.number_input("Rendimento do Gap (% a.a.)", min_value=0.0, value=10.0, step=0.1, format="%.2f")
    taxa_desc = st.number_input("Taxa de Desconto (% a.a.) para VPL", min_value=0.0, value=10.0, step=0.1, format="%.2f")
    calcular = st.button("Calcular")

if not calcular:
    st.info("Preencha os parâmetros e clique em **Calcular**.")
    st.stop()

# ─── 1) Financiamento ───────────────────────────────────────────────────────────
PV = valor - entrada
r_mens = (1 + juros_ano/100)**(1/12) - 1
n_fin = int(prazo_fin)
meses_fin = np.arange(1, n_fin+1)

# gera parcelas
A_price = PV * r_mens / (1 - (1 + r_mens)**(-n_fin))
df_price = pd.DataFrame(index=meses_fin, columns=["Parcela"], dtype=float)
bal = PV
for m in meses_fin:
    j = bal * r_mens
    am = A_price - j
    bal -= am
    df_price.loc[m, "Parcela"] = A_price

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
# escolhe índice
if idx_choice=="Fixo 5%":
    def factor(m): return (1.05)**((m-1)//12)
    factors = [factor(m) for m in range(1, prazo_cons+1)]
else:
    series_map = {"IPCA":"433","INPC":"188","IGP-M":"189"}
    end = datetime.today().strftime("%d/%m/%Y")
    start_dt = datetime.today() - timedelta(days= prazo_cons*31 )
    start = start_dt.strftime("%d/%m/%Y")
    idx_series = fetch_index(series_map[idx_choice], start, end)
    fac = idx_series.reindex(pd.date_range(idx_series.index[0], idx_series.index[-1], freq='M')).fillna(method='ffill')
    factors = fac.values[:prazo_cons].tolist()

parc_cons = [base_cons * f for f in factors]
df_cons = pd.DataFrame({"Parcela":parc_cons}, index=np.arange(1, prazo_cons+1))

# ─── 3) Tabela Totais ─────────────────────────────────────────────────────────
total_fin = df_fin["Parcela"].sum() + entrada
total_cons = df_cons["Parcela"].sum()
df_resumo = pd.DataFrame({
    "Alternativa":["Financiamento","Consórcio"],
    "Total Pago (R$)":[total_fin, total_cons]
})
df_resumo["Total Pago (R$)"] = df_resumo["Total Pago (R$)"].map(format_brl)
st.subheader("Total Pago")
st.table(df_resumo.set_index("Alternativa"))

# ─── 4) Fluxo de Caixa Acumulado ────────────────────────────────────────────────
# CF: entry + parcels
cf_fin = [-entrada] + [-v for v in df_fin["Parcela"].tolist()]
cf_cons = [0] + [-v for v in df_cons["Parcela"].tolist()]
# pad to same length
L = max(len(cf_fin), len(cf_cons))
cf_fin += [0]*(L - len(cf_fin))
cf_cons += [0]*(L - len(cf_cons))
cumsum_fin = np.cumsum(cf_fin)
cumsum_cons = np.cumsum(cf_cons)
df_cf = pd.DataFrame({
    "Mês": np.arange(0, L),
    "Financiamento": cumsum_fin,
    "Consórcio": cumsum_cons
})
fig_cf = px.line(df_cf, x="Mês", y=["Financiamento","Consórcio"],
                 title="Fluxo de Caixa Acumulado",
                 template="plotly_white")
fig_cf.update_layout(yaxis_tickformat=",.0f")
st.subheader("Fluxo de Caixa Acumulado")
st.plotly_chart(fig_cf, use_container_width=True)

# ─── 5) VPL e TIR ───────────────────────────────────────────────────────────────
r_desc_m = (1 + taxa_desc/100)**(1/12) - 1
# NPV
npv_fin = sum(cf_fin[t]/((1+r_desc_m)**t) for t in range(L))
npv_cons= sum(cf_cons[t]/((1+r_desc_m)**t) for t in range(L))
# IRR mensal → anual
irr_fin = np.irr(cf_fin)
irr_cons= np.irr(cf_cons)
tir_fin = (1+irr_fin)**12-1 if irr_fin else None
tir_cons= (1+irr_cons)**12-1 if irr_cons else None

c1,c2,c3,c4 = st.columns(4)
c1.metric("VPL Financiamento", format_brl(npv_fin))
c2.metric("VPL Consórcio", format_brl(npv_cons))
c3.metric("TIR Financiamento", f"{tir_fin*100:.2f}%")
c4.metric("TIR Consórcio", f"{tir_cons*100:.2f}%")

# ─── 6) Comparação de Parcelas c/ alertas ───────────────────────────────────────
length = max(len(df_fin), len(df_cons))
x = np.arange(1, length+1)
fin_pad = list(df_fin["Parcela"]) + [None]*(length-len(df_fin))
cons_pad= list(df_cons["Parcela"])+ [None]*(length-len(df_cons))
gap = np.array([ (f or 0)-(c or 0) for f,c in zip(fin_pad,cons_pad)])
# detecta inversão de sinal
flips = [i+1 for i in range(1,len(gap)) if np.sign(gap[i])!=np.sign(gap[i-1])]

fig = go.Figure()
fig.add_trace(go.Bar(x=x, y=cons_pad, name="Consórcio", marker_color="#00FFC2", width=0.6))
fig.add_trace(go.Bar(x=x, y=fin_pad if modelo_fin=="Price" else None,
                     name="Financiamento", marker_color="#2081E2", width=0.6))
fig.update_layout(template="plotly_dark", barmode="overlay",
                  title="Parcelas vs. Consórcio com Alertas", bargap=0.15)
# anotações para flips
for m in flips:
    fig.add_vline(x=m, line_dash="dash", line_color="yellow",
                  annotation_text=f"Mudança de sinal: mês {m}", annotation_position="top right")
st.subheader("Parcelas & Alertas")
st.plotly_chart(fig, use_container_width=True)

# ─── 7) Metodologia ────────────────────────────────────────────────────────────
with st.expander("📌 Metodologia"):
    st.markdown("""
- **Fluxo de Caixa Acumulado**: mostra o saldo cumulativo de pagamentos e entrada.  
- **VPL**: valor presente líquido descontado à taxa informada.  
- **TIR**: taxa interna de retorno anualizada.  
- **Índice de Reajuste**: escolha entre fixo, IPCA, INPC ou IGP-M (via API BCB).  
- **Alertas**: marca meses em que o gap parcela-financ./consórcio muda de sinal.
""")
