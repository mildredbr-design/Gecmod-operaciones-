import streamlit as st
import pandas as pd
import pathlib
from datetime import date, datetime, timedelta
import calendar
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 10

st.set_page_config(page_title="Simulador Joker", layout="wide")
st.title("Simulador Joker — Revolving")

# ---------------------------------------------------------
# CARGA FECHAS DE BLOQUEO
# Archivo: COFES_01_Date_Blocage.txt (misma carpeta que este script)
# Formato: una fecha por linea DD/MM/YYYY
# ---------------------------------------------------------

_DIR = pathlib.Path(__file__).parent


def _leer_fechas_bloqueo():
    fechas = []
    ruta = _DIR / "COFES_01_Date_Blocage.txt"
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    fechas.append(datetime.strptime(linea, "%d/%m/%Y").date())
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return sorted(fechas)


fechas_bloqueo_global = _leer_fechas_bloqueo()

if not fechas_bloqueo_global:
    st.warning("No se encontro COFES_01_Date_Blocage.txt. Sube el fichero manualmente.")
    fichero_subido = st.file_uploader("Subir COFES_01_Date_Blocage.txt", type=["txt"])
    if fichero_subido:
        for linea in fichero_subido.read().decode("utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                fechas_bloqueo_global.append(datetime.strptime(linea, "%d/%m/%Y").date())
            except ValueError:
                pass
        fechas_bloqueo_global = sorted(fechas_bloqueo_global)
        if fechas_bloqueo_global:
            st.success(f"{len(fechas_bloqueo_global)} fechas de bloqueo cargadas.")


def fecha_bloqueo_para_mes(fecha_recibo):
    for fb in fechas_bloqueo_global:
        if fb.year == fecha_recibo.year and fb.month == fecha_recibo.month:
            return fb
    return fecha_recibo - timedelta(days=2)


# ---------------------------------------------------------
# FUNCIONES AUXILIARES
# ---------------------------------------------------------

def dias_ano_real(fecha):
    return 366 if calendar.isleap(fecha.year) else 365


def crear_fecha_recibo(fecha_base, dia):
    ultimo_dia = calendar.monthrange(fecha_base.year, fecha_base.month)[1]
    return date(fecha_base.year, fecha_base.month, min(dia, ultimo_dia))


def siguiente_mes_fecha(fecha, dia=None):
    """Si se pasa dia, usa ese dia en vez de fecha.day."""
    d = dia if dia is not None else fecha.day
    if fecha.month == 12:
        return date(fecha.year + 1, 1, d)
    return date(fecha.year, fecha.month + 1, d)


def primer_recibo(fecha_inicio, dia_recibo):
    fecha_recibo = crear_fecha_recibo(fecha_inicio, dia_recibo)
    if fecha_recibo <= fecha_inicio:
        fecha_recibo = crear_fecha_recibo(siguiente_mes_fecha(fecha_inicio, 1), dia_recibo)
    return fecha_recibo


def recibo_siguiente(fecha_recibo, dia_recibo):
    return crear_fecha_recibo(siguiente_mes_fecha(fecha_recibo, dia_recibo), dia_recibo)


# ---------------------------------------------------------
# INTERESES REVOLVING: dias reales / ano real (365 o 366)
# ---------------------------------------------------------

def interes_periodo(capital, tin, fecha_ini, fecha_fin):
    capital = Decimal(str(capital))
    tin_dec = Decimal(str(tin)) / Decimal("100")
    dias = Decimal(str((fecha_fin - fecha_ini).days))
    base = Decimal(str(dias_ano_real(fecha_ini)))
    return (capital * tin_dec * dias / base).quantize(Decimal("0.00001"))


# ---------------------------------------------------------
# JOKER: a que recibo aplica
#   - Por defecto, al recibo inmediato siguiente a la orden.
#   - Si la orden es igual o posterior a la fecha de bloqueo de ese
#     recibo, aplica al recibo siguiente.
# Devuelve (recibo_joker, recibo_inmediato, bloqueo_inmediato)
# ---------------------------------------------------------

def determinar_recibo_joker(fecha_joker, fecha_inicio, dia_recibo):
    recibo_inmediato = primer_recibo(fecha_inicio, dia_recibo)
    while recibo_inmediato <= fecha_joker:
        recibo_inmediato = recibo_siguiente(recibo_inmediato, dia_recibo)

    fb_inmediato = fecha_bloqueo_para_mes(recibo_inmediato)
    if fecha_joker < fb_inmediato:
        recibo_joker = recibo_inmediato
    else:
        recibo_joker = recibo_siguiente(recibo_inmediato, dia_recibo)

    return recibo_joker, recibo_inmediato, fb_inmediato


# ---------------------------------------------------------
# SIMULADOR
# ---------------------------------------------------------

def simulador(capital, tin, cuota_mensual, fecha_inicio, dia_recibo,
              seguro_tasa, fecha_joker_recibo=None):
    """
    Recibo Joker: no se cobra nada al cliente (ni cuota ni seguro).
    Los intereses del periodo se calculan y se suman al capital pendiente,
    de modo que el recibo siguiente calcula intereses sobre capital + intereses.
    """
    saldo = Decimal(str(capital))
    seguro_tasa = Decimal(str(seguro_tasa))
    cuota = Decimal(str(cuota_mensual)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    fecha_recibo = primer_recibo(fecha_inicio, dia_recibo)
    fecha_anterior = fecha_inicio
    datos = []
    mes = 1

    while saldo > 0:
        fb = fecha_bloqueo_para_mes(fecha_recibo)
        dias = (fecha_recibo - fecha_anterior).days
        capital_inicio = saldo

        interes = interes_periodo(saldo, tin, fecha_anterior, fecha_recibo)
        interes = interes.quantize(Decimal("0.01"), ROUND_HALF_UP)

        es_joker = fecha_joker_recibo is not None and fecha_recibo == fecha_joker_recibo

        if es_joker:
            capitalizado = interes
            saldo = saldo + interes
            amort = Decimal("0")
            cuota_final = Decimal("0")
            seguro = Decimal("0")
        else:
            capitalizado = Decimal("0")
            seguro = ((saldo + interes) * seguro_tasa).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            if saldo + interes <= cuota:
                amort = saldo
                saldo = Decimal("0")
                cuota_final = amort + interes
            else:
                amort = cuota - interes
                if amort < 0:
                    amort = Decimal("0")
                saldo = saldo - amort
                cuota_final = cuota

        datos.append({
            "Mes": mes,
            "Fecha recibo": fecha_recibo.strftime("%d/%m/%Y"),
            "Fecha bloqueo": fb.strftime("%d/%m/%Y"),
            "Joker": "Si" if es_joker else "",
            "Dias": dias,
            "Base interes": f"Real/{dias_ano_real(fecha_anterior)}",
            "Capital pendiente (EUR)": float(capital_inicio),
            "Intereses (EUR)": float(interes),
            "Intereses capitalizados (EUR)": float(capitalizado),
            "Cuota (EUR)": float(cuota_final),
            "Amortizacion (EUR)": float(amort),
            "Saldo (EUR)": float(saldo),
            "Seguro (EUR)": float(seguro),
            "Recibo total (EUR)": float(cuota_final + seguro),
        })

        fecha_anterior = fecha_recibo
        fecha_recibo = recibo_siguiente(fecha_recibo, dia_recibo)
        mes += 1

        if mes > 600:
            break

    return pd.DataFrame(datos)


# ---------------------------------------------------------
# INPUTS
# ---------------------------------------------------------

col1, col2 = st.columns(2)

with col1:
    capital = st.number_input(
        "Capital pendiente (EUR)",
        min_value=0.0, max_value=1_000_000.0, value=6000.0,
        step=0.01, format="%.2f"
    )
    tin = st.number_input("TIN anual (%)", 0.0, 100.0, 21.79)
    fecha_inicio = st.date_input(
        "Fecha de ultimo recibo / Fecha de financiacion",
        datetime.today(), format="DD/MM/YYYY"
    )
    dia_recibo = st.selectbox("Dia del recibo", list(range(1, 29)))

with col2:
    cuota_input = st.number_input(
        "Cuota mensual (EUR)",
        min_value=0.0, max_value=100_000.0, value=180.0,
        step=0.01, format="%.2f"
    )
    opciones_seguro = {
        "No": 0,
        "Un titular Light": 0.0035,
        "Un titular Full/Senior": 0.0061,
        "Dos titulares Full/Full": 0.0104,
        "Dos titulares Light/Light": 0.0059,
    }
    seguro_str = st.selectbox("Seguro", list(opciones_seguro.keys()))
    seguro_tasa = opciones_seguro[seguro_str]

st.divider()
st.subheader("Joker")
st.caption(
    "El Joker aplica al recibo inmediato siguiente a la orden. "
    "Si la orden es igual o posterior a la fecha de bloqueo de ese recibo, "
    "aplica al recibo siguiente. En el recibo Joker el cliente no paga nada "
    "y los intereses del periodo se suman al capital pendiente."
)

aplicar_joker = st.checkbox("Aplicar Joker")
fecha_joker = None
if aplicar_joker:
    fecha_joker = st.date_input(
        "Fecha de la orden del Joker", fecha_inicio, format="DD/MM/YYYY"
    )


# ---------------------------------------------------------
# RESULTADO
# ---------------------------------------------------------

recibo_joker = None
if fecha_joker is not None:
    recibo_joker, recibo_inmediato, fb_inmediato = determinar_recibo_joker(
        fecha_joker, fecha_inicio, dia_recibo
    )
    if recibo_joker == recibo_inmediato:
        motivo = (
            f"la orden es anterior a la fecha de bloqueo "
            f"({fb_inmediato:%d/%m/%Y}) del recibo inmediato"
        )
    else:
        motivo = (
            f"la orden es igual o posterior a la fecha de bloqueo "
            f"({fb_inmediato:%d/%m/%Y}) del recibo del {recibo_inmediato:%d/%m/%Y}"
        )
    st.info(
        f"Orden Joker: {fecha_joker:%d/%m/%Y}. "
        f"El Joker se aplica en el recibo del {recibo_joker:%d/%m/%Y} porque {motivo}."
    )

df = simulador(
    capital, tin, cuota_input, fecha_inicio, dia_recibo,
    seguro_tasa, recibo_joker
)

if df.empty:
    st.warning("No hay recibos que mostrar: el capital pendiente es 0.")
else:
    if recibo_joker is not None:
        fila = df[df["Joker"] == "Si"]
        if fila.empty:
            st.warning(
                f"El credito se cancela antes del recibo del {recibo_joker:%d/%m/%Y}; "
                "el Joker no llega a aplicarse."
            )
        else:
            fila = fila.iloc[0]
            m1, m2, m3 = st.columns(3)
            m1.metric("Capital antes del Joker", f"{fila['Capital pendiente (EUR)']:,.2f} EUR")
            m2.metric("Intereses capitalizados", f"{fila['Intereses capitalizados (EUR)']:,.2f} EUR")
            m3.metric("Capital tras el Joker", f"{fila['Saldo (EUR)']:,.2f} EUR")

    columnas_eur = [c for c in df.columns if "(EUR)" in c]

    def _resaltar_joker(row):
        color = "background-color: #f9eeda" if row["Joker"] == "Si" else ""
        return [color] * len(row)

    st.subheader("Cuadro de amortizacion")
    st.dataframe(
        df.style.apply(_resaltar_joker, axis=1)
               .format({c: "{:,.2f}" for c in columnas_eur}),
        hide_index=True, use_container_width=True
    )

    t1, t2, t3 = st.columns(3)
    t1.metric("Numero de recibos", len(df))
    t2.metric("Total intereses", f"{df['Intereses (EUR)'].sum():,.2f} EUR")
    t3.metric("Total pagado", f"{df['Recibo total (EUR)'].sum():,.2f} EUR")
