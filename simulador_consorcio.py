import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(layout="wide", page_title="Simulador Consórcio vs Financiamento")

def format_brl(x):
    # recebe float e retorna string “R$ 1.234,56”
    s = f"{x:,.2f}"
    s = s.replace(",", "v").replace(".", ",").replace("v", ".")
    return f"R$ {s}"

st.title("Simulador Consórcio vs Financiamento")
st.markdown(
    "Compare o consórcio (reajuste 5% a.a.) com o modelo de financiamento de sua escolha "
    "e veja o break-even investindo a diferença a uma taxa configurável."
)

# ─── Sidebar de parâmetros ───────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parâmetros de Entrada")
    valor = st.number_input(
        "Valor Necessário (R$)", min_value=0.0, value=500_000.00,
        step=1_000.00, format="%.2f"
    )
    entrada = st.number_input(
        "Entrada (R$)", min_value=0.0, value=100_000.00,
        step=1_000.00, format="%.2f"
    )
    juros_ano = st.number_input(
        "Juros do Financiamento ao Ano (%)", min_value=0.0,
        value=8.0, step=0.1, format="%.2f"
    )
    prazo_fin = st.number_input(
        "Prazo do Financiamento (meses)", min_value=1,
        value=120, step=1
    )
    modelo_fin = st.selectbox("Comparar consórcio com:", ["Price", "SAC"])

    # agora dinâmico também
    prazo_cons = st.number_input(
        "Prazo do Consórcio (meses)", min_value=1,
        value=180, step=1
    )
    st.markdown(
        f"**Consórcio:** {prazo_cons} meses; taxa adm. 20% + reserva 3% (única vez); "
        "reajuste anual fixo de **5%**."
    )

    # NOVO INPUT: taxa de rendimento anual do gap
    taxa_gap = st.number_input(
        "Rendimento do Gap (% a.a.)",
        min_value=0.0, value=10.0,
        step=0.1, format="%.2f",
        help="Taxa anual em que você vai investir a diferença das parcelas"
    )

    st.markdown("💡 Invista o gap mensal à taxa anual acima para calcular o break-even.")
    calcular = st.button("Calcular")

if not calcular:
    st.info("Ajuste os parâmetros na lateral e clique em **Calcular**.")
    st.stop()

# ─── 1) Financiamento (Price / SAC) ─────────────────────────────────────────────
PV = valor - entrada
r_ano = juros_ano / 100
i = (1 + r_ano) ** (1/12) - 1
n_fin = int(prazo_fin)
meses_fin = np.arange(1, n_fin + 1)

# Price
A_price = PV * i / (1 - (1 + i) ** (-n_fin))
df_price = pd.DataFrame(index=meses_fin, columns=["Parcela"])
bal = PV
for m in meses_fin:
    j = bal * i
    am = A_price - j
    bal -= am
    df_price.loc[m, "Parcela"] = A_price

# SAC
amort = PV / n_fin
df_sac = pd.DataFrame(index=meses_fin, columns=["Parcela"])
bal = PV
for m in meses_fin:
    j = bal * i
    pmt = amort + j
    bal -= amort
    df_sac.loc[m, "Parcela"] = pmt

df_fin = df_price if modelo_fin == "Price" else df_sac

# ─── 2) Consórcio ───────────────────────────────────────────────────────────────
base_cons = valor * 1.23 / prazo_cons  # +20% adm +3% reserva
parc_cons = [
    base_cons * (1.05 ** ((m-1)//12))
    for m in range(1, prazo_cons + 1)
]
df_cons = pd.DataFrame({"Parcela": parc_cons}, index=np.arange(1, prazo_cons + 1))

# ─── 3) Totais Pagos ────────────────────────────────────────────────────────────
total_fin = df_fin["Parcela"].sum() + entrada
total_cons = df_cons["Parcela"].sum()
df_resumo = pd.DataFrame({
    "Modelo": [modelo_fin, "Consórcio"],
    "Total Pago (R$)": [total_fin, total_cons]
}).set_index("Modelo")

# aplica formatação brasileira
df_resumo_fmt = df_resumo.copy()
df_resumo_fmt["Total Pago (R$)"] = df_resumo["Total Pago (R$)"].apply(format_brl)

st.subheader("Quanto pagaria em cada caso?")
st.table(df_resumo_fmt)

# ─── 4) Gráfico de Parcelas ────────────────────────────────────────────────────
df_plot = pd.DataFrame({
    "Mês": list(df_fin.index) + list(df_cons.index),
    "Parcela (R$)": list(df_fin["Parcela"]) + list(df_cons["Parcela"]),
    "Modelo": [modelo_fin]*len(df_fin) + ["Consórcio"]*len(df_cons)
})
fig1 = px.line(
    df_plot, x="Mês", y="Parcela (R$)", color="Modelo",
    title=f"Parcelas: Consórcio vs {modelo_fin}",
    template="plotly_white"
)
fig1.update_traces(line=dict(width=3))
fig1.update_layout(
    xaxis_title="Mês",
    yaxis_tickformat=",.0f",
    margin=dict(t=60, b=40)
)
st.subheader("Comparação de Parcelas")
st.plotly_chart(fig1, use_container_width=True)

# ─── 5) Simulação do Investimento do GAP ────────────────────────────────────────
mensal_gap = (1 + taxa_gap/100) ** (1/12) - 1

length = max(len(df_fin), len(df_cons))
fin_pad  = list(df_fin["Parcela"])  + [0.0]*(length - len(df_fin))
cons_pad = list(df_cons["Parcela"]) + [0.0]*(length - len(df_cons))
gap = np.array(fin_pad) - np.array(cons_pad)

saldo, contribs, juros = [], [], []
bal_inv, be = 0.0, None
for m, g in enumerate(gap, start=1):
    cont = max(g, 0.0)
    interest = bal_inv * mensal_gap
    bal_inv = bal_inv + interest + g
    contribs.append(cont)
    juros.append(interest)
    saldo.append(bal_inv)
    if be is None and bal_inv <= 0:
        be = m

# ─── 6) Métricas de Investimento ───────────────────────────────────────────────
total_investido = sum(contribs)
total_rendimento = sum(juros)
if be:
    inv_be = sum(contribs[:be])
    rend_be = sum(juros[:be])
else:
    inv_be, rend_be = total_investido, total_rendimento

c1, c2, c3 = st.columns(3)
c1.metric("Break-even (mês)", f"{be}" if be else "Não ocorreu")
c2.metric("Total investido (R$)", format_brl(inv_be))
c3.metric("Total rendimento (R$)", format_brl(rend_be))

# ─── 7) Gráfico do Saldo Investido ─────────────────────────────────────────────
df_inv = pd.DataFrame({
    "Mês": np.arange(1, length+1),
    "Saldo Investido (R$)": saldo
})
fig2 = px.line(
    df_inv, x="Mês", y="Saldo Investido (R$)",
    title="Saldo do Investimento das Diferenças",
    template="plotly_white"
)
fig2.update_traces(line=dict(width=3))
fig2.update_layout(
    xaxis_title="Mês",
    yaxis_tickformat=",.0f",
    margin=dict(t=60, b=40)
)
if be:
    fig2.add_vline(
        x=be, line_dash="dash", line_color="red",
        annotation_text=f"Break-even: mês {be}",
        annotation_position="top right"
    )
st.subheader("Investindo a Diferença do Gap")
st.plotly_chart(fig2, use_container_width=True)

# ─── 8) Metodologia ────────────────────────────────────────────────────────────
with st.expander("📌 Metodologia"):
    st.markdown(f"""
- **Gap** = parcela financiamento – parcela consórcio.  
- **Investimento** do gap mensal a {taxa_gap:.2f}% a.a. (composto).  
- **Break-even**: primeiro mês em que o saldo investido zera ou fica negativo.  
- **Total Investido**: soma das contribuições positivas até o break-even  
  (ou até o final, se não ocorrer).  
- **Total Rendimento**: soma dos juros até o break-even  
  (ou até o final, se não ocorrer).  
- **Consórcio**: prazo definido; taxa admin. 20% + reserva 3%; reajuste 5% a.a.  
- **Financiamento**: escolha entre Price ou SAC.
""")
