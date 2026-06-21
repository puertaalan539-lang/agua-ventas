"""
app.py
Interfaz principal Streamlit para el sistema de ventas de agua purificada.
Ejecutar: streamlit run app.py
"""

import streamlit as st
from datetime import date, timedelta
import database as db
import ocr_extractor as ocr
import reportes

# ──────────────────────────────────────────────
# CONFIG PÁGINA
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Agua Purificada — Ventas",
    page_icon="💧",
    layout="wide",
)

# Inicializar BD una sola vez
db.init_db()

# ──────────────────────────────────────────────
# SIDEBAR — Fecha de trabajo
# ──────────────────────────────────────────────
st.sidebar.title("💧 Control de Ventas")
fecha_sel = st.sidebar.date_input("📅 Fecha del registro", value=date.today())
st.sidebar.markdown("---")
pagina = st.sidebar.radio(
    "Sección",
    ["📋 Registro de Locales", "🧴 Ventas Individuales",
     "💸 Gastos del Día",     "📊 Reportes"],
)

# ══════════════════════════════════════════════
# SECCIÓN 1: REGISTRO DE LOCALES (OCR + Manual)
# ══════════════════════════════════════════════
if pagina == "📋 Registro de Locales":
    st.title(f"📋 Registro de Locales — {fecha_sel}")

    locales  = db.get_locales()
    nombres  = [l["nombre"] for l in locales]
    ids_map  = {l["nombre"]: l["id"] for l in locales}

    # Precios globales del día (se aplican a todos los locales)
    st.subheader("💲 Precios del Día")
    col1, col2, col3 = st.columns(3)
    p_garr = col1.number_input("Precio Garrafón $",       min_value=0.0, value=14.0, step=0.5)
    p_med  = col2.number_input("Precio Medio Garrafón $", min_value=0.0, value=7.0, step=0.5)
    p_gal  = col3.number_input("Precio Galón $",          min_value=0.0, value=4.0,  step=0.5)

    st.markdown("---")

    # ── Tabs: OCR y Manual ──
    tab_ocr, tab_manual = st.tabs(["📷 Cargar Foto (OCR)", "✏️ Entrada Manual"])

    # ── TAB OCR ──
    with tab_ocr:
        st.info("Sube las 3 fotos de la pantalla del dispensador (Producto 1, 2 y 3). "
                "El sistema lee NO.venta y Dinero de cada una automáticamente.")

        local_ocr = st.selectbox("Local", nombres, key="sel_ocr")
        motor_ocr = st.radio("Motor OCR", ["tesseract", "google"], horizontal=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.caption("📸 Producto 1 — Garrafón")
            foto1 = st.file_uploader("Foto", type=["jpg","jpeg","png","webp"], key="foto1")
            if foto1: st.image(foto1, width=200)
        with c2:
            st.caption("📸 Producto 2 — Medio Garrafón")
            foto2 = st.file_uploader("Foto", type=["jpg","jpeg","png","webp"], key="foto2")
            if foto2: st.image(foto2, width=200)
        with c3:
            st.caption("📸 Producto 3 — Galón")
            foto3 = st.file_uploader("Foto", type=["jpg","jpeg","png","webp"], key="foto3")
            if foto3: st.image(foto3, width=200)

        if foto1 or foto2 or foto3:
            if st.button("🔍 Procesar las 3 fotos"):
                imagenes = {}
                if foto1: imagenes[1] = foto1.getvalue()
                if foto2: imagenes[2] = foto2.getvalue()
                if foto3: imagenes[3] = foto3.getvalue()

                with st.spinner("Leyendo pantallas..."):
                    resultado = ocr.procesar_local_completo(imagenes, motor=motor_ocr)

                if resultado.advertencias:
                    for a in resultado.advertencias:
                        st.warning(a)
                else:
                    st.success("✅ Las 3 pantallas se leyeron correctamente.")

                st.subheader("Verificar y corregir datos extraídos")
                st.caption("NO.venta = unidades vendidas | Dinero = total acumulado en el contador")

                cc1, cc2, cc3 = st.columns(3)
                g_uds  = cc1.number_input("Garrafón — unidades",       value=resultado.garrafon_no_venta, min_value=0)
                mg_uds = cc2.number_input("Medio Garrafón — unidades", value=resultado.medio_no_venta,    min_value=0)
                ga_uds = cc3.number_input("Galón — unidades",          value=resultado.galon_no_venta,    min_value=0)

                cc4, cc5, cc6 = st.columns(3)
                g_din  = cc4.number_input("Garrafón — $ contador",       value=resultado.garrafon_dinero, min_value=0.0)
                mg_din = cc5.number_input("Medio Garrafón — $ contador", value=resultado.medio_dinero,    min_value=0.0)
                ga_din = cc6.number_input("Galón — $ contador",          value=resultado.galon_dinero,    min_value=0.0)

                total_contador = g_din + mg_din + ga_din
                st.metric("💰 Total según contador (Dinero acumulado)", f"${total_contador:,.2f}")

                with st.expander("Ver texto crudo OCR de cada pantalla"):
                    for i, lec in enumerate(resultado.lecturas, start=1):
                        st.markdown(f"**Foto {i}** — confianza: {lec.confianza}")
                        st.code(lec.texto_crudo)

                if st.button("💾 Guardar datos OCR"):
                    db.upsert_venta_local(
                        ids_map[local_ocr], fecha_sel,
                        g_uds, mg_uds, ga_uds, p_garr, p_med, p_gal,
                        fuente="ocr",
                        notas=f"Lectura contador: ${total_contador:,.2f}"
                    )
                    st.success(f"✅ Datos de {local_ocr} guardados.")

    # ── TAB MANUAL ──
    with tab_manual:
        st.subheader("Ingreso manual por local")

        for nombre in nombres:
            with st.expander(f"🏪 {nombre}"):
                c1, c2, c3 = st.columns(3)
                g  = c1.number_input("Garrafón",       key=f"g_{nombre}",  min_value=0)
                mg = c2.number_input("Medio Garrafón", key=f"mg_{nombre}", min_value=0)
                ga = c3.number_input("Galón",          key=f"ga_{nombre}", min_value=0)

                total_prev = g * p_garr + mg * p_med + ga * p_gal
                st.caption(f"Total estimado: **${total_prev:.2f}**")

                notas = st.text_input("Notas (opcional)", key=f"n_{nombre}")

                if st.button(f"💾 Guardar {nombre}", key=f"btn_{nombre}"):
                    db.upsert_venta_local(
                        ids_map[nombre], fecha_sel,
                        g, mg, ga, p_garr, p_med, p_gal,
                        fuente="manual", notas=notas
                    )
                    st.success(f"✅ {nombre} guardado.")

    # Tabla resumen del día
    st.markdown("---")
    st.subheader("📊 Resumen del Día")
    ventas_hoy = db.get_ventas_por_fecha(fecha_sel)
    if ventas_hoy:
        import pandas as pd
        df = pd.DataFrame([dict(v) for v in ventas_hoy])
        cols = ["local_nombre", "garrafon", "medio_garrafon", "galon", "total_bruto", "fuente"]
        df = df[cols].rename(columns={
            "local_nombre": "Local", "garrafon": "Garrafón",
            "medio_garrafon": "Medio Garrafón", "galon": "Galón",
            "total_bruto": "Total Bruto $", "fuente": "Fuente"
        })
        st.dataframe(df, use_container_width=True)
        st.metric("💰 Total Bruto del Día", f"${df['Total Bruto $'].sum():,.2f}")
    else:
        st.info("Sin ventas registradas para esta fecha.")


# ══════════════════════════════════════════════
# SECCIÓN 2: VENTAS INDIVIDUALES
# ══════════════════════════════════════════════
elif pagina == "🧴 Ventas Individuales":
    st.title(f"🧴 Ventas Individuales — {fecha_sel}")
    st.info("Registra aquí garrafones vendidos fuera de los locales.")

    with st.form("form_individual"):
        c1, c2, c3, c4 = st.columns(4)
        producto   = c1.selectbox("Producto", ["garrafon", "medio_garrafon", "galon"])
        cantidad   = c2.number_input("Cantidad", min_value=1, value=1)
        precio_u   = c3.number_input("Precio unitario $", min_value=0.0, value=25.0, step=0.5)
        notas      = c4.text_input("Notas")
        submitted  = st.form_submit_button("➕ Agregar venta")

    if submitted:
        db.insert_venta_individual(fecha_sel, producto, cantidad, precio_u, notas)
        st.success(f"✅ Venta de {cantidad} {producto.replace('_',' ')} registrada.")
        st.rerun()

    # Lista del día
    ventas_i = db.get_ventas_individuales_fecha(fecha_sel)
    if ventas_i:
        import pandas as pd
        df_i = pd.DataFrame([dict(v) for v in ventas_i])
        df_i["producto"] = df_i["producto"].str.replace("_", " ").str.title()
        st.dataframe(df_i[["id","producto","cantidad","precio_unit","total","notas"]],
                     use_container_width=True)

        st.metric("Total Ventas Individuales", f"${df_i['total'].sum():,.2f}")

        eliminar_id = st.number_input("ID a eliminar", min_value=0, step=1)
        if st.button("🗑️ Eliminar") and eliminar_id:
            db.delete_venta_individual(eliminar_id)
            st.rerun()
    else:
        st.info("Sin ventas individuales para esta fecha.")


# ══════════════════════════════════════════════
# SECCIÓN 3: GASTOS
# ══════════════════════════════════════════════
elif pagina == "💸 Gastos del Día":
    st.title(f"💸 Gastos del Día — {fecha_sel}")
    st.caption("Los porcentajes de reparto deben sumar exactamente 100%.")

    with st.form("form_gasto"):
        descripcion = st.text_input("Descripción del gasto", placeholder="Ej: Gasolina repartidor")
        monto       = st.number_input("Monto total $", min_value=0.0, step=10.0)

        st.markdown("**Distribución entre productos:**")
        c1, c2, c3 = st.columns(3)
        pct_g  = c1.slider("% Garrafón",        0, 100, 60)
        pct_mg = c2.slider("% Medio Garrafón",  0, 100, 25)
        pct_ga = c3.slider("% Galón",           0, 100, 15)
        total_pct = pct_g + pct_mg + pct_ga

        if total_pct != 100:
            st.error(f"Los porcentajes suman {total_pct}%. Deben ser exactamente 100%.")

        submitted = st.form_submit_button("➕ Agregar gasto")

    if submitted and total_pct == 100 and monto > 0:
        db.insert_gasto(
            fecha_sel, descripcion, monto,
            pct_g / 100, pct_mg / 100, pct_ga / 100
        )
        st.success("✅ Gasto registrado.")
        st.rerun()

    # Lista de gastos
    gastos = db.get_gastos_fecha(fecha_sel)
    if gastos:
        import pandas as pd
        df_g = pd.DataFrame([dict(g) for g in gastos])
        df_g["% Garrafón"]       = (df_g["porc_garrafon"] * 100).astype(int).astype(str) + "%"
        df_g["% Medio Garrafón"] = (df_g["porc_medio"]    * 100).astype(int).astype(str) + "%"
        df_g["% Galón"]          = (df_g["porc_galon"]    * 100).astype(int).astype(str) + "%"
        st.dataframe(df_g[["id","descripcion","monto_total","% Garrafón","% Medio Garrafón","% Galón"]],
                     use_container_width=True)
        st.metric("Total Gastos del Día", f"${df_g['monto_total'].sum():,.2f}")

        del_id = st.number_input("ID de gasto a eliminar", min_value=0, step=1)
        if st.button("🗑️ Eliminar gasto") and del_id:
            db.delete_gasto(del_id)
            st.rerun()
    else:
        st.info("Sin gastos registrados para esta fecha.")


# ══════════════════════════════════════════════
# SECCIÓN 4: REPORTES
# ══════════════════════════════════════════════
elif pagina == "📊 Reportes":
    st.title("📊 Generación de Reportes")

    tab_d, tab_s = st.tabs(["📄 Reporte Diario", "📅 Reporte Semanal"])

    with tab_d:
        st.subheader(f"Reporte del día: {fecha_sel}")
        if st.button("⬇️ Generar Excel Diario"):
            with st.spinner("Generando..."):
                ruta = reportes.generar_reporte_diario(fecha_sel)
            with open(ruta, "rb") as f:
                st.download_button(
                    label="📥 Descargar Excel",
                    data=f.read(),
                    file_name=ruta.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    with tab_s:
        st.subheader("Reporte Semanal (últimos 7 días desde fecha seleccionada)")
        if st.button("⬇️ Generar Excel Semanal"):
            with st.spinner("Agrupando datos de la semana..."):
                ruta = reportes.generar_reporte_semanal(fecha_sel)
            with open(ruta, "rb") as f:
                st.download_button(
                    label="📥 Descargar Excel Semanal",
                    data=f.read(),
                    file_name=ruta.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )