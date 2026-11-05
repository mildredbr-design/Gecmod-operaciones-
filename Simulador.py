import streamlit as st
import pandas as pd
import pathlib
from datetime import date, datetime, timedelta
import calendar
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 10

st.set_page_config(page_title="Simulador Joker y cambio de dia", layout="wide")
st.title("Simulador Joker y cambio de dia — Revolving")

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
# CARGA PORCENTAJES DE CUOTA
# Archivo: porcentajes_cuota.txt (misma carpeta que este script)
# Formato: un porcentaje por linea, p. ej. 3 / 3,5 / 3.5 / 3,5%
#          (3 = 3 % del capital inicial de apertura)
# ---------------------------------------------------------

FICHERO_PORCENTAJES = "porcentajes_cuota.txt"


def _parsear_porcentajes(lineas):
    porcentajes = set()
    for linea in lineas:
        linea = linea.strip().replace("%", "").replace(",", ".").strip()
        if not linea:
            continue
        try:
            valor = Decimal(linea)
        except Exception:
            continue
        if valor > 0:
            porcentajes.add(valor)
    return sorted(porcentajes)


def _leer_porcentajes():
    ruta = _DIR / FICHERO_PORCENTAJES
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return _parsear_porcentajes(f.readlines())
    except FileNotFoundError:
        return []


porcentajes_cuota = _leer_porcentajes()


def cuota_desde_porcentaje(capital_inicial, porcentaje):
    return (Decimal(str(capital_inicial)) * Decimal(str(porcentaje)) / Decimal("100")).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )


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


def ultimo_recibo_hasta(fecha, dia_recibo):
    """Ultimo recibo pasado en o antes de 'fecha' (inicio del periodo de intereses)."""
    fecha_recibo = crear_fecha_recibo(fecha, dia_recibo)
    if fecha_recibo > fecha:
        if fecha.month == 1:
            mes_anterior = date(fecha.year - 1, 12, 1)
        else:
            mes_anterior = date(fecha.year, fecha.month - 1, 1)
        fecha_recibo = crear_fecha_recibo(mes_anterior, dia_recibo)
    return fecha_recibo


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
# REGLA DE BLOQUEO (Joker y cambio de dia de pago)
#   Una orden aplica al primer recibo posterior a la orden cuya
#   fecha de bloqueo sea posterior a la orden:
#   - Orden anterior al bloqueo del recibo inmediato -> ese recibo.
#   - Orden igual o posterior a ese bloqueo -> el recibo siguiente.
# ---------------------------------------------------------

def aplica_en_recibo(fecha_orden, fecha_recibo):
    """True si la orden afecta a este recibo; False si llega tarde (bloqueo)."""
    fb = fecha_bloqueo_para_mes(fecha_recibo)
    return fecha_orden < fb and fecha_orden < fecha_recibo


# ---------------------------------------------------------
# SIMULADOR
# ---------------------------------------------------------

def simulador(capital, tin, cuota_mensual, fecha_inicio, dia_recibo,
              seguro_tasa, fecha_joker=None, cambio_dia=None,
              cambio_cuota=None):
    """
    fecha_joker: fecha de la orden del Joker o None.
      Recibo Joker: no se cobra nada al cliente (ni cuota ni seguro).
      Los intereses del periodo se suman al capital pendiente.

    cambio_dia: (fecha_peticion, nuevo_dia) o None.
      El recibo afectado se mueve al nuevo dia dentro de su mismo mes y los
      intereses se calculan desde el recibo anterior hasta la nueva fecha
      (un solo bloque, dias reales / 365 o 366). Los recibos siguientes
      pasan todos al nuevo dia.

    cambio_cuota: (fecha_peticion, nueva_cuota) o None.
      Misma regla de bloqueo. Desde el recibo afectado se cobra la nueva
      cuota; los intereses no cambian, cambia el capital amortizado.

    Devuelve (DataFrame, avisos) donde avisos describe a que recibo
    aplico cada operacion y si se salto alguno por la fecha de bloqueo.
    """
    saldo = Decimal(str(capital))
    seguro_tasa = Decimal(str(seguro_tasa))
    cuota = Decimal(str(cuota_mensual)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    dia_actual = dia_recibo
    fecha_recibo = primer_recibo(fecha_inicio, dia_actual)
    fecha_anterior = fecha_inicio
    datos = []
    avisos = {}
    mes = 1

    joker_pendiente = fecha_joker is not None
    cambio_pendiente = cambio_dia is not None
    cuota_pendiente = cambio_cuota is not None

    while saldo > 0:

        # -------- CAMBIO DE DIA DE PAGO --------
        hay_cambio = False
        if cambio_pendiente:
            fecha_peticion, nuevo_dia = cambio_dia
            if aplica_en_recibo(fecha_peticion, fecha_recibo):
                recibo_original = fecha_recibo
                fecha_recibo = crear_fecha_recibo(fecha_recibo, nuevo_dia)
                # Si la nueva fecha ya ha pasado, se va al mes siguiente
                if fecha_recibo <= max(fecha_anterior, fecha_peticion):
                    fecha_recibo = recibo_siguiente(fecha_recibo, nuevo_dia)
                dia_actual = nuevo_dia
                hay_cambio = True
                cambio_pendiente = False
                avisos["cambio_dia"] = (recibo_original, fecha_recibo)
            elif fecha_peticion < fecha_recibo:
                avisos["cambio_dia_saltado"] = (
                    fecha_recibo, fecha_bloqueo_para_mes(fecha_recibo)
                )

        fb = fecha_bloqueo_para_mes(fecha_recibo)

        # -------- CAMBIO DE MENSUALIDAD --------
        hay_cambio_cuota = False
        if cuota_pendiente:
            fecha_peticion_c, nueva_cuota = cambio_cuota
            if aplica_en_recibo(fecha_peticion_c, fecha_recibo):
                cuota_anterior = cuota
                cuota = Decimal(str(nueva_cuota)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                hay_cambio_cuota = True
                cuota_pendiente = False
                avisos["cambio_cuota"] = (fecha_recibo, cuota_anterior, cuota)
            elif fecha_peticion_c < fecha_recibo:
                avisos["cambio_cuota_saltado"] = (fecha_recibo, fb)

        # -------- JOKER --------
        es_joker = False
        if joker_pendiente:
            if aplica_en_recibo(fecha_joker, fecha_recibo):
                es_joker = True
                joker_pendiente = False
                avisos["joker"] = fecha_recibo
            elif fecha_joker < fecha_recibo:
                avisos["joker_saltado"] = (fecha_recibo, fb)

        # -------- INTERESES: recibo anterior -> recibo actual --------
        dias = (fecha_recibo - fecha_anterior).days
        capital_inicio = saldo

        interes = interes_periodo(saldo, tin, fecha_anterior, fecha_recibo)
        interes = interes.quantize(Decimal("0.01"), ROUND_HALF_UP)

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
            "Cambio dia": "Si" if hay_cambio else "",
            "Cambio cuota": "Si" if hay_cambio_cuota else "",
            "Desde": fecha_anterior.strftime("%d/%m/%Y"),
            "Dias": dias,
            "Base interes": f"Real/{dias_ano_real(fecha_anterior)}",
            "Capital pendiente (EUR)": float(capital_inicio),
            "Intereses (EUR)": float(interes),
            "Intereses capitalizados (EUR)": float(capitalizado),
            "Cuota contrato (EUR)": float(cuota),
            "Cuota (EUR)": float(cuota_final),
            "Amortizacion (EUR)": float(amort),
            "Saldo (EUR)": float(saldo),
            "Seguro (EUR)": float(seguro),
            "Recibo total (EUR)": float(cuota_final + seguro),
        })

        fecha_anterior = fecha_recibo
        fecha_recibo = recibo_siguiente(fecha_recibo, dia_actual)
        mes += 1

        if mes > 600:
            break

    return pd.DataFrame(datos), avisos


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
    fecha_simulacion = st.date_input("Fecha de simulacion", datetime.today())
    dia_recibo = st.selectbox("Dia del recibo", list(range(1, 29)))
    # Los intereses se calculan siempre desde el ultimo recibo pasado
    fecha_inicio = ultimo_recibo_hasta(fecha_simulacion, dia_recibo)
    st.caption(
        f"Recibo anterior: {fecha_inicio:%d/%m/%Y}. "
        "El capital pendiente es el que queda tras ese recibo."
    )

with col2:
    capital_inicial = st.number_input(
        "Capital inicial de apertura (EUR)",
        min_value=0.0, max_value=1_000_000.0, value=6000.0,
        step=0.01, format="%.2f",
        help="Base para calcular las cuotas: capital inicial x porcentaje del fichero."
    )
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
st.caption(
    "Joker, cambio de dia de pago y cambio de mensualidad aplican al recibo "
    "inmediato siguiente a la orden. Si la orden es igual o posterior a la fecha "
    "de bloqueo de ese recibo, aplican al recibo siguiente. "
    "Se pueden simular por separado o juntos."
)

colj, colc, colm = st.columns(3)

with colj:
    st.subheader("Joker")
    aplicar_joker = st.radio(
        "Aplicar Joker", ["No", "Si"], horizontal=True, key="aplicar_joker"
    )
    fecha_joker = None
    if aplicar_joker == "Si":
        fecha_joker = st.date_input(
            "Fecha de la orden del Joker", fecha_simulacion, key="fecha_joker"
        )
        st.caption(
            "En el recibo Joker el cliente no paga nada y los intereses "
            "del periodo se suman al capital pendiente."
        )

with colc:
    st.subheader("Cambio de dia de pago")
    aplicar_cambio = st.radio(
        "Aplicar cambio de dia", ["No", "Si"], horizontal=True, key="aplicar_cambio"
    )
    cambio_dia = None
    if aplicar_cambio == "Si":
        nuevo_dia = st.selectbox(
            "Nuevo dia de recibo", list(range(1, 29)), key="nuevo_dia"
        )
        fecha_cambio = st.date_input(
            "Fecha de la peticion del cambio", fecha_simulacion, key="fecha_cambio"
        )
        cambio_dia = (fecha_cambio, nuevo_dia)
        st.caption(
            "Los intereses del recibo afectado se calculan desde el recibo "
            "anterior hasta la nueva fecha de recibo."
        )

with colm:
    st.subheader("Cambio de mensualidad")
    aplicar_cuota = st.radio(
        "Aplicar cambio de mensualidad", ["No", "Si"], horizontal=True,
        key="aplicar_cuota"
    )
    cambio_cuota = None
    if aplicar_cuota == "Si":
        if not porcentajes_cuota:
            st.warning(f"No se encontro {FICHERO_PORCENTAJES}. Sube el fichero manualmente.")
            fichero_pct = st.file_uploader(
                f"Subir {FICHERO_PORCENTAJES}", type=["txt"], key="fichero_pct"
            )
            if fichero_pct:
                porcentajes_cuota = _parsear_porcentajes(
                    fichero_pct.read().decode("utf-8").splitlines()
                )
                if porcentajes_cuota:
                    st.success(f"{len(porcentajes_cuota)} porcentajes cargados.")

        cuota_desplegable = None
        if porcentajes_cuota:
            opciones_cuota = {
                f"{cuota_desde_porcentaje(capital_inicial, p):,.2f} EUR "
                f"({str(p).replace('.', ',')} %)": p
                for p in porcentajes_cuota
            }
            etiqueta = st.selectbox(
                "Nueva mensualidad", list(opciones_cuota.keys()), key="nueva_cuota"
            )
            cuota_desplegable = cuota_desde_porcentaje(
                capital_inicial, opciones_cuota[etiqueta]
            )

        # Mensualidad forzada: si se rellena, tiene prioridad sobre el desplegable
        texto_forzada = st.text_input(
            "Mensualidad forzada (EUR)", value="", key="cuota_forzada",
            help="Opcional. Si se rellena, se usa este importe en lugar del desplegable."
        )
        cuota_forzada = None
        if texto_forzada.strip():
            try:
                cuota_forzada = Decimal(
                    texto_forzada.strip().replace(".", "").replace(",", ".")
                    if "," in texto_forzada else texto_forzada.strip()
                ).quantize(Decimal("0.01"), ROUND_HALF_UP)
                if cuota_forzada <= 0:
                    raise ValueError
            except Exception:
                cuota_forzada = None
                st.error("Mensualidad forzada no valida. Usa un importe como 175,50.")

        if cuota_forzada is not None:
            nueva_cuota = cuota_forzada
            origen = "mensualidad forzada"
        elif cuota_desplegable is not None:
            nueva_cuota = cuota_desplegable
            origen = f"desplegable: capital inicial ({capital_inicial:,.2f} EUR) x porcentaje"
        else:
            nueva_cuota = None

        if nueva_cuota is not None:
            fecha_cambio_cuota = st.date_input(
                "Fecha de la peticion del cambio", fecha_simulacion,
                key="fecha_cambio_cuota"
            )
            cambio_cuota = (fecha_cambio_cuota, nueva_cuota)
            st.caption(
                f"Nueva mensualidad: {nueva_cuota:,.2f} EUR ({origen}). "
                "Los intereses no cambian; cambia el capital amortizado."
            )
        else:
            st.caption("Elige una mensualidad del desplegable o rellena la mensualidad forzada.")


# ---------------------------------------------------------
# RESULTADO
# ---------------------------------------------------------

df, avisos = simulador(
    capital, tin, cuota_input, fecha_inicio, dia_recibo,
    seguro_tasa, fecha_joker, cambio_dia, cambio_cuota
)

if cambio_cuota is not None:
    if "cambio_cuota" in avisos:
        recibo_c, cuota_ant, cuota_nueva = avisos["cambio_cuota"]
        texto = (
            f"Cambio de mensualidad pedido el {cambio_cuota[0]:%d/%m/%Y}: desde el recibo "
            f"del {recibo_c:%d/%m/%Y} la cuota pasa de {cuota_ant:,.2f} EUR "
            f"a {cuota_nueva:,.2f} EUR."
        )
        if "cambio_cuota_saltado" in avisos:
            saltado, fb_s = avisos["cambio_cuota_saltado"]
            texto += (
                f" No afecta al recibo del {saltado:%d/%m/%Y} porque la peticion es "
                f"igual o posterior a su fecha de bloqueo ({fb_s:%d/%m/%Y})."
            )
        st.info(texto)
    else:
        st.warning("El credito se cancela antes de que el cambio de mensualidad llegue a aplicarse.")

if cambio_dia is not None:
    if "cambio_dia" in avisos:
        original, nuevo = avisos["cambio_dia"]
        texto = (
            f"Cambio de dia pedido el {cambio_dia[0]:%d/%m/%Y}: el recibo del "
            f"{original:%d/%m/%Y} pasa al {nuevo:%d/%m/%Y}."
        )
        if "cambio_dia_saltado" in avisos:
            saltado, fb_s = avisos["cambio_dia_saltado"]
            texto += (
                f" No afecta al recibo del {saltado:%d/%m/%Y} porque la peticion es "
                f"igual o posterior a su fecha de bloqueo ({fb_s:%d/%m/%Y})."
            )
        st.info(texto)
    else:
        st.warning("El credito se cancela antes de que el cambio de dia llegue a aplicarse.")

if fecha_joker is not None:
    if "joker" in avisos:
        texto = (
            f"Orden Joker: {fecha_joker:%d/%m/%Y}. El Joker se aplica en el recibo "
            f"del {avisos['joker']:%d/%m/%Y}."
        )
        if "joker_saltado" in avisos:
            saltado, fb_s = avisos["joker_saltado"]
            texto += (
                f" No afecta al recibo del {saltado:%d/%m/%Y} porque la orden es "
                f"igual o posterior a su fecha de bloqueo ({fb_s:%d/%m/%Y})."
            )
        st.info(texto)
    else:
        st.warning("El credito se cancela antes de que el Joker llegue a aplicarse.")

if df.empty:
    st.warning("No hay recibos que mostrar: el capital pendiente es 0.")
else:
    fila = df[df["Joker"] == "Si"]
    if not fila.empty:
        fila = fila.iloc[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("Capital antes del Joker", f"{fila['Capital pendiente (EUR)']:,.2f} EUR")
        m2.metric("Intereses capitalizados", f"{fila['Intereses capitalizados (EUR)']:,.2f} EUR")
        m3.metric("Capital tras el Joker", f"{fila['Saldo (EUR)']:,.2f} EUR")

    st.subheader("Cuadro de amortizacion")
    st.dataframe(df.round(2))

    t1, t2, t3 = st.columns(3)
    t1.metric("Numero de recibos", len(df))
    t2.metric("Total intereses", f"{df['Intereses (EUR)'].sum():,.2f} EUR")
    t3.metric("Total pagado", f"{df['Recibo total (EUR)'].sum():,.2f} EUR")
