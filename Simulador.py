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
              cambio_cuota=None, disposicion=None,
              pct_inicial=None, base_cuota="inicial", capital_inicial=None):
    """
    fecha_joker: fecha de la orden del Joker o None.
      Recibo Joker: no se cobra nada al cliente (ni cuota ni seguro).
      Los intereses del periodo se suman al capital pendiente.

    cambio_dia: (fecha_peticion, nuevo_dia) o None.
      El recibo afectado se mueve al nuevo dia dentro de su mismo mes y los
      intereses se calculan desde el recibo anterior hasta la nueva fecha
      (un solo bloque, dias reales / 365 o 366). Los recibos siguientes
      pasan todos al nuevo dia.

    cambio_cuota: (fecha_peticion, tipo, valor) o None.
      tipo = "pct"     -> valor es un porcentaje; la cuota se calcula sobre la base
      tipo = "importe" -> valor es una mensualidad forzada en EUR
      Misma regla de bloqueo. Desde el recibo afectado se cobra la nueva
      cuota; los intereses no cambian, cambia el capital amortizado.

    pct_inicial: porcentaje con el que se calcula la cuota actual, o None si
      la cuota es manual (forzada).
    base_cuota: "inicial"   -> cuota = capital inicial de apertura x porcentaje
                "pendiente" -> cuota = capital pendiente (+ disposicion) x porcentaje
      Con base "pendiente" y cuota por porcentaje, una disposicion recalcula la
      cuota: antes del bloqueo, desde ese mismo recibo; igual o posterior al
      bloqueo, desde el recibo siguiente. Una cuota forzada no se recalcula.

    disposicion: (fecha_disposicion, importe) o None.
      - Antes de la fecha de bloqueo del recibo: el periodo se divide en dos.
          Tramo 1: capital pendiente x dias (recibo anterior -> disposicion)
          Tramo 2: (capital + disposicion) x dias (disposicion -> recibo)
      - Igual o posterior al bloqueo: el recibo ya esta emitido y sus
        intereses no cambian (capital pendiente x periodo completo). Los
        intereses del importe dispuesto desde la disposicion hasta el recibo
        se suman a los intereses del recibo siguiente.
      En ambos casos el capital pendiente sube con la disposicion en ese recibo.

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
    dispo_pendiente = disposicion is not None
    reg_intereses = Decimal("0")  # intereses de disposicion tras bloqueo, para el recibo siguiente

    pct_actual = Decimal(str(pct_inicial)) if pct_inicial is not None else None
    cap_inicial = Decimal(str(capital_inicial if capital_inicial is not None else capital))
    cuota_diferida = None  # recalculo por disposicion tras bloqueo, para el recibo siguiente

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

        # -------- RECALCULO DE CUOTA DIFERIDO (disposicion tras bloqueo) --------
        marca_cuota = ""
        if cuota_diferida is not None:
            avisos["recalculo_cuota"]["recibo"] = fecha_recibo
            avisos["recalculo_cuota"]["cuota_ant"] = cuota
            cuota = cuota_diferida
            cuota_diferida = None
            marca_cuota = "Recalculo disposicion"

        # -------- CAMBIO DE MENSUALIDAD --------
        if cuota_pendiente:
            fecha_peticion_c, tipo_c, valor_c = cambio_cuota
            if aplica_en_recibo(fecha_peticion_c, fecha_recibo):
                cuota_anterior = cuota
                if tipo_c == "pct":
                    pct_actual = Decimal(str(valor_c))
                    base_c = cap_inicial if base_cuota == "inicial" else saldo
                    cuota = cuota_desde_porcentaje(base_c, pct_actual)
                else:
                    pct_actual = None
                    base_c = None
                    cuota = Decimal(str(valor_c)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                marca_cuota = "Peticion"
                cuota_pendiente = False
                avisos["cambio_cuota"] = (fecha_recibo, cuota_anterior, cuota, base_c)
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

        importe_dispo = Decimal("0")
        reg_siguiente = Decimal("0")
        if dispo_pendiente and fecha_anterior <= disposicion[0] < fecha_recibo:
            fecha_dispo = disposicion[0]
            importe_dispo = Decimal(str(disposicion[1])).quantize(Decimal("0.01"), ROUND_HALF_UP)
            dispo_pendiente = False
            if fecha_dispo < fb:
                # Dos periodos dentro del mismo recibo
                interes_t1 = interes_periodo(saldo, tin, fecha_anterior, fecha_dispo)
                interes_t2 = interes_periodo(saldo + importe_dispo, tin, fecha_dispo, fecha_recibo)
                interes = interes_t1 + interes_t2
                avisos["disposicion"] = {
                    "tipo": "antes", "recibo": fecha_recibo, "bloqueo": fb,
                    "t1": (fecha_anterior, fecha_dispo, saldo, interes_t1),
                    "t2": (fecha_dispo, fecha_recibo, saldo + importe_dispo, interes_t2),
                }
            else:
                # Recibo emitido: no se tocan sus intereses; regularizacion al mes siguiente
                interes = interes_periodo(saldo, tin, fecha_anterior, fecha_recibo)
                reg_siguiente = interes_periodo(importe_dispo, tin, fecha_dispo, fecha_recibo)
                avisos["disposicion"] = {
                    "tipo": "despues", "recibo": fecha_recibo, "bloqueo": fb,
                    "reg": (fecha_dispo, fecha_recibo, importe_dispo,
                            reg_siguiente.quantize(Decimal("0.01"), ROUND_HALF_UP)),
                }
        else:
            interes = interes_periodo(saldo, tin, fecha_anterior, fecha_recibo)

        # Regularizacion de una disposicion tras bloqueo del recibo anterior
        reg_aplicada = reg_intereses.quantize(Decimal("0.01"), ROUND_HALF_UP)
        interes += reg_intereses
        reg_intereses = reg_siguiente

        interes = interes.quantize(Decimal("0.01"), ROUND_HALF_UP)
        saldo += importe_dispo

        # -------- RECALCULO DE CUOTA POR DISPOSICION --------
        # Base "capital pendiente": cuota = (capital pendiente + disposicion) x porcentaje
        if importe_dispo > 0 and base_cuota == "pendiente" and pct_actual is not None:
            nueva = cuota_desde_porcentaje(saldo, pct_actual)
            avisos["recalculo_cuota"] = {
                "base": saldo, "pct": pct_actual, "nueva": nueva,
                "recibo": None, "cuota_ant": cuota,
            }
            if disposicion[0] < fb:
                avisos["recalculo_cuota"]["recibo"] = fecha_recibo
                cuota = nueva
                marca_cuota = "Recalculo disposicion"
            else:
                cuota_diferida = nueva

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
            "Cambio cuota": marca_cuota,
            "Desde": fecha_anterior.strftime("%d/%m/%Y"),
            "Dias": dias,
            "Base interes": f"Real/{dias_ano_real(fecha_anterior)}",
            "Capital pendiente (EUR)": float(capital_inicio),
            "Disposicion (EUR)": float(importe_dispo),
            "Intereses (EUR)": float(interes),
            "Regul. disposicion (EUR)": float(reg_aplicada),
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
# TAE (misma funcion que el simulador original)
# ---------------------------------------------------------

def calcular_tae(flujos, fechas):
    tiempos = [0.0]
    for i in range(1, len(fechas)):
        f0 = fechas[i - 1]
        f1 = fechas[i]
        fraccion = (f1 - f0).days / dias_ano_real(f0)
        tiempos.append(tiempos[-1] + fraccion)

    def van(tasa):
        return sum(c / ((1 + tasa) ** t) for c, t in zip(flujos, tiempos))

    minimo, maximo = -0.9999, 10.0
    for _ in range(1000):
        medio = (minimo + maximo) / 2
        v = van(medio)
        if abs(v) < 1e-10:
            return round(medio * 100, 2)
        if v > 0:
            minimo = medio
        else:
            maximo = medio
    return round(medio * 100, 2)


def tae_del_cuadro(df, capital, fecha_inicio, disposicion_aplicada=None):
    """
    Flujos: - capital pendiente en la fecha del recibo anterior,
            - importe dispuesto en la fecha de la disposicion (si la hay),
            + cuota cobrada en cada recibo (0 en el recibo Joker).
    Devuelve None si el credito no llega a amortizarse.
    """
    if df.empty or df["Saldo (EUR)"].iloc[-1] > 0:
        return None
    movimientos = [(fecha_inicio, -float(capital))]
    if disposicion_aplicada is not None:
        movimientos.append((disposicion_aplicada[0], -float(disposicion_aplicada[1])))
    for _, fila in df.iterrows():
        fecha = datetime.strptime(fila["Fecha recibo"], "%d/%m/%Y").date()
        movimientos.append((fecha, float(fila["Cuota (EUR)"])))
    movimientos.sort(key=lambda m: m[0])
    return calcular_tae([m[1] for m in movimientos], [m[0] for m in movimientos])


# ---------------------------------------------------------
# INPUTS
# ---------------------------------------------------------

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


def etiqueta_pct(p):
    return f"{str(p).replace('.', ',')} %"


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

    base_str = st.radio(
        "Base de calculo de la cuota",
        ["Capital inicial de apertura", "Capital pendiente + disposicion"],
        key="base_cuota",
        help=(
            "Capital inicial: cuota = capital inicial x porcentaje. "
            "Capital pendiente + disposicion: cuota = capital pendiente x porcentaje, "
            "y se recalcula al hacer una disposicion."
        )
    )
    base_cuota = "inicial" if base_str == "Capital inicial de apertura" else "pendiente"

    modo_cuota = st.radio(
        "Calculo de la cuota", ["Por porcentaje", "Manual (forzada)"],
        horizontal=True, key="modo_cuota"
    )
    pct_inicial = None
    if modo_cuota == "Por porcentaje" and porcentajes_cuota:
        base_actual = capital_inicial if base_cuota == "inicial" else capital
        opciones_pct = {
            f"{etiqueta_pct(p)} -> {cuota_desde_porcentaje(base_actual, p):,.2f} EUR": p
            for p in porcentajes_cuota
        }
        etiqueta_ini = st.selectbox(
            "Porcentaje de la cuota", list(opciones_pct.keys()), key="pct_inicial"
        )
        pct_inicial = opciones_pct[etiqueta_ini]
        cuota_input = float(cuota_desde_porcentaje(base_actual, pct_inicial))
        st.caption(
            f"Cuota: {cuota_input:,.2f} EUR = "
            f"{'capital inicial' if base_cuota == 'inicial' else 'capital pendiente'} "
            f"({base_actual:,.2f} EUR) x {etiqueta_pct(pct_inicial)}."
        )
    else:
        if modo_cuota == "Por porcentaje":
            st.caption("Sin fichero de porcentajes: introduce la cuota manualmente.")
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

st.subheader("Disposicion")
aplicar_dispo = st.radio(
    "Hacer disposicion", ["No", "Si"], horizontal=True, key="aplicar_dispo"
)
disposicion = None
if aplicar_dispo == "Si":
    cd1, cd2 = st.columns(2)
    with cd1:
        importe_dispo_input = st.number_input(
            "Importe de la disposicion (EUR)",
            min_value=0.0, max_value=1_000_000.0, value=500.0,
            step=0.01, format="%.2f", key="importe_dispo"
        )
    with cd2:
        fecha_dispo_input = st.date_input(
            "Fecha de la disposicion", fecha_simulacion, key="fecha_dispo"
        )
    if importe_dispo_input > 0:
        disposicion = (fecha_dispo_input, importe_dispo_input)
    st.caption(
        "Antes del bloqueo: intereses en dos periodos (capital pendiente hasta la "
        "disposicion; capital + disposicion desde la disposicion hasta el recibo). "
        "Igual o posterior al bloqueo: el recibo no cambia y los intereses del importe "
        "dispuesto hasta el recibo se suman al recibo siguiente."
    )

st.divider()

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
        pct_desplegable = None
        if porcentajes_cuota:
            base_ref = capital_inicial if base_cuota == "inicial" else capital
            opciones_cuota = {
                f"{cuota_desde_porcentaje(base_ref, p):,.2f} EUR ({etiqueta_pct(p)})": p
                for p in porcentajes_cuota
            }
            etiqueta = st.selectbox(
                "Nueva mensualidad", list(opciones_cuota.keys()), key="nueva_cuota"
            )
            pct_desplegable = opciones_cuota[etiqueta]
            if base_cuota == "pendiente":
                st.caption(
                    "Importes calculados sobre el capital pendiente actual; el simulador "
                    "usa el capital pendiente del recibo en que se aplique el cambio."
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
            tipo_nueva, valor_nueva = "importe", cuota_forzada
            origen = f"mensualidad forzada de {cuota_forzada:,.2f} EUR"
        elif pct_desplegable is not None:
            tipo_nueva, valor_nueva = "pct", pct_desplegable
            origen = (
                f"{etiqueta_pct(pct_desplegable)} del "
                f"{'capital inicial' if base_cuota == 'inicial' else 'capital pendiente'}"
            )
        else:
            tipo_nueva = None

        if tipo_nueva is not None:
            fecha_cambio_cuota = st.date_input(
                "Fecha de la peticion del cambio", fecha_simulacion,
                key="fecha_cambio_cuota"
            )
            cambio_cuota = (fecha_cambio_cuota, tipo_nueva, valor_nueva)
            st.caption(
                f"Nueva mensualidad: {origen}. "
                "Los intereses no cambian; cambia el capital amortizado."
            )
        else:
            st.caption("Elige una mensualidad del desplegable o rellena la mensualidad forzada.")


# ---------------------------------------------------------
# RESULTADO
# ---------------------------------------------------------

df, avisos = simulador(
    capital, tin, cuota_input, fecha_inicio, dia_recibo,
    seguro_tasa, fecha_joker, cambio_dia, cambio_cuota, disposicion,
    pct_inicial, base_cuota, capital_inicial
)

if "recalculo_cuota" in avisos:
    rc = avisos["recalculo_cuota"]
    if rc["recibo"] is not None:
        st.info(
            f"Recalculo de cuota por disposicion: (capital pendiente + disposicion) "
            f"{rc['base']:,.2f} EUR x {etiqueta_pct(rc['pct'])} = {rc['nueva']:,.2f} EUR. "
            f"Desde el recibo del {rc['recibo']:%d/%m/%Y} la cuota pasa de "
            f"{rc['cuota_ant']:,.2f} EUR a {rc['nueva']:,.2f} EUR."
        )
elif disposicion is not None and base_cuota == "pendiente" and pct_inicial is None \
        and not (cambio_cuota is not None and cambio_cuota[1] == "pct"):
    st.caption("La cuota es manual (forzada): la disposicion no recalcula la cuota.")

if disposicion is not None:
    info = avisos.get("disposicion")
    if info is None:
        st.warning(
            "La fecha de la disposicion es anterior al recibo anterior o el credito "
            "se cancela antes; la disposicion no se aplica."
        )
    elif info["tipo"] == "antes":
        d1, h1, c1, i1 = info["t1"]
        d2, h2, c2, i2 = info["t2"]
        st.info(
            f"Disposicion de {disposicion[1]:,.2f} EUR el {disposicion[0]:%d/%m/%Y}, "
            f"anterior al bloqueo ({info['bloqueo']:%d/%m/%Y}): los intereses del recibo del "
            f"{info['recibo']:%d/%m/%Y} se calculan en dos periodos.  \n"
            f"Periodo 1: {d1:%d/%m/%Y} a {h1:%d/%m/%Y} ({(h1 - d1).days} dias) sobre "
            f"{c1:,.2f} EUR = {i1:,.2f} EUR.  \n"
            f"Periodo 2: {d2:%d/%m/%Y} a {h2:%d/%m/%Y} ({(h2 - d2).days} dias) sobre "
            f"{c2:,.2f} EUR = {i2:,.2f} EUR."
        )
    else:
        dd, hh, imp, reg = info["reg"]
        st.info(
            f"Disposicion de {disposicion[1]:,.2f} EUR el {disposicion[0]:%d/%m/%Y}, "
            f"igual o posterior al bloqueo ({info['bloqueo']:%d/%m/%Y}): el recibo del "
            f"{info['recibo']:%d/%m/%Y} ya esta emitido y sus intereses no cambian.  \n"
            f"Intereses del importe dispuesto del {dd:%d/%m/%Y} al {hh:%d/%m/%Y} "
            f"({(hh - dd).days} dias): {imp:,.2f} EUR = {reg:,.2f} EUR, que se suman "
            f"a los intereses del recibo siguiente."
        )

if cambio_cuota is not None:
    if "cambio_cuota" in avisos:
        recibo_c, cuota_ant, cuota_nueva, base_c = avisos["cambio_cuota"]
        calculo = ""
        if base_c is not None:
            calculo = f" ({base_c:,.2f} EUR x {etiqueta_pct(cambio_cuota[2])})"
        texto = (
            f"Cambio de mensualidad pedido el {cambio_cuota[0]:%d/%m/%Y}: desde el recibo "
            f"del {recibo_c:%d/%m/%Y} la cuota pasa de {cuota_ant:,.2f} EUR "
            f"a {cuota_nueva:,.2f} EUR{calculo}."
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

    # -------- TAE original (sin operaciones) y CER (con las operaciones) --------
    df_original, _ = simulador(
        capital, tin, cuota_input, fecha_inicio, dia_recibo, seguro_tasa,
        pct_inicial=pct_inicial, base_cuota=base_cuota, capital_inicial=capital_inicial
    )
    tae_original = tae_del_cuadro(df_original, capital, fecha_inicio)

    hay_operaciones = any(
        x is not None for x in (fecha_joker, cambio_dia, cambio_cuota, disposicion)
    )
    dispo_aplicada = disposicion if "disposicion" in avisos else None
    cer = tae_del_cuadro(df, capital, fecha_inicio, dispo_aplicada) if hay_operaciones else None

    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("Numero de recibos", len(df))
    t2.metric("Total intereses", f"{df['Intereses (EUR)'].sum():,.2f} EUR")
    t3.metric("Total pagado", f"{df['Recibo total (EUR)'].sum():,.2f} EUR")
    t4.metric("TAE original", f"{tae_original:.2f} %" if tae_original is not None else "n/d")
    if not hay_operaciones:
        t5.metric("CER", "Sin cambios")
    else:
        t5.metric(
            "CER", f"{cer:.2f} %" if cer is not None else "n/d",
            delta=(f"{cer - tae_original:+.2f} pp"
                   if cer is not None and tae_original is not None else None),
            delta_color="off"
        )
    st.caption(
        "TAE original: cuadro sin operaciones. CER: recalculada con las operaciones "
        "simuladas (Joker, cambio de dia, cambio de mensualidad, disposicion). "
        "Flujos: capital pendiente y disposicion entregados; cuotas cobradas (sin seguro). "
        "n/d: el credito no se amortiza en 600 recibos."
    )
