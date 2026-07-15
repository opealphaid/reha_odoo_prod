import logging
import base64
from io import BytesIO
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak, \
        KeepTogether
    from reportlab.pdfgen import canvas
    import qrcode
except ImportError:
    _logger.error("ReportLab o qrcode no están instalados. Instale: pip install reportlab qrcode[pil]")


class NumberedCanvas(canvas.Canvas):

    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        """Dibuja el número de página en la esquina inferior derecha"""
        self.setFont("Helvetica", 8)
        page_num = f"Página {self._pageNumber} de {page_count}"
        # Posición: 15mm desde el borde derecho, 8mm desde abajo
        self.drawRightString(letter[0] - 15 * mm, 8 * mm, page_num)


class AccountMove(models.Model):
    _inherit = 'account.move'

    siat_pdf_factura = fields.Binary(
        string='PDF Factura SIAT',
        readonly=True,
        copy=False,
        attachment=True,
        help='PDF de la factura SIAT generada'
    )

    siat_pdf_filename = fields.Char(
        string='Nombre PDF',
        compute='_compute_siat_pdf_filename',
        store=True
    )

    @api.depends('name', 'siat_numero_factura')
    def _compute_siat_pdf_filename(self):
        for move in self:
            if move.siat_numero_factura:
                move.siat_pdf_filename = f'Factura_SIAT_{move.siat_numero_factura}.pdf'
            else:
                move.siat_pdf_filename = f'Factura_{move.name}.pdf'

    def action_generar_pdf_siat(self):
        """Genera el PDF de la factura SIAT"""
        self.ensure_one()

        if not self.siat_facturado:
            raise UserError(
                "FACTURA NO ENVIADA A SIAT\n\n"
                "Esta factura aún no ha sido enviada a SIAT.\n"
                "No se puede generar el PDF."
            )

        try:
            pdf_data = self._generar_pdf_factura_siat()

            self.write({
                'siat_pdf_factura': base64.b64encode(pdf_data)
            })

            _logger.info(f"✓ PDF generado para factura {self.name}")

            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/account.move/{self.id}/siat_pdf_factura/{self.siat_pdf_filename}?download=true',
                'target': 'self',
            }

        except Exception as e:
            _logger.error(f"Error generando PDF: {str(e)}", exc_info=True)
            raise UserError(f"Error al generar PDF: {str(e)}")

    def _generar_pdf_factura_siat(self):
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=12 * mm,
            leftMargin=12 * mm,
            topMargin=10 * mm,
            bottomMargin=15 * mm
        )

        story = []
        styles = getSampleStyleSheet()

        # Estilos
        style_title = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=14,
            textColor=colors.HexColor('#000000'),
            spaceAfter=6,
            spaceBefore=0,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )

        style_subtitle = ParagraphStyle(
            'subtitle',
            parent=styles['Normal'],
            fontSize=9,
            alignment=TA_CENTER,
            spaceAfter=0,
            spaceBefore=0
        )

        style_normal = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=8,
            alignment=TA_LEFT
        )

        encabezado_data = [
            [
                self._get_logo_empresa(),
                self._get_datos_empresa(),
                self._get_datos_factura_box()
            ]
        ]

        encabezado_table = Table(encabezado_data, colWidths=[55 * mm, 75 * mm, 60 * mm])
        encabezado_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ]))

        story.append(encabezado_table)
        story.append(Spacer(1, 3 * mm))

        story.append(Paragraph("FACTURA", style_title))
        story.append(Paragraph("(Con Derecho a Crédito Fiscal)", style_subtitle))
        story.append(Spacer(1, 2 * mm))

        cliente_data = self._get_datos_cliente()
        cliente_table = Table(cliente_data, colWidths=[45 * mm, 100 * mm, 40 * mm])
        cliente_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ]))

        story.append(cliente_table)
        story.append(Spacer(1, 2 * mm))

        # FILTRAR: Excluir línea de descuento global del detalle
        productos = [
            line for line in self.invoice_line_ids 
            if line.product_id and line.product_id.default_code != 'global_discount'
        ]
        
        productos_por_pagina = 10
        total_productos = len(productos)

        for i in range(0, total_productos, productos_por_pagina):
            productos_bloque = productos[i:i + productos_por_pagina]
            es_ultima_pagina = (i + productos_por_pagina) >= total_productos

            detalle_table = self._get_tabla_detalle_bloque(productos_bloque)
            story.append(detalle_table)
            story.append(Spacer(1, 2 * mm))

            footer_elements = []

            totales_table = self._get_tabla_totales()
            footer_elements.append(totales_table)

            if self.siat_es_moneda_extranjera:
                footer_elements.append(Spacer(1, 2 * mm))

                style_nota_tc = ParagraphStyle(
                    'NotaTipoCambio',
                    parent=style_normal,
                    fontSize=7,
                    alignment=TA_LEFT,
                    textColor=colors.HexColor('#000000')
                )

                tipo_cambio_fmt = self._formatear_numero(self.siat_tipo_cambio, 2)
                moneda_codigo = self.currency_id.name

                nota_tc = (
                    f"SOLO PARA EFECTOS DE CRÉDITO FISCAL AL TIPO DE CAMBIO "
                    f"Bs. {tipo_cambio_fmt} POR {moneda_codigo} 1,00."
                )

                footer_elements.append(Paragraph(nota_tc, style_nota_tc))

                _logger.info(f"Nota de tipo de cambio agregada: {nota_tc}")

            footer_elements.append(Spacer(1, 2 * mm))

            monto_letras = self._convertir_monto_a_letras(self.amount_total)
            footer_elements.append(Paragraph(f"<b>Son:</b> {monto_letras}", style_normal))
            footer_elements.append(Spacer(1, 2 * mm))

            qr_y_textos = self._get_qr_y_textos_layout()
            footer_elements.append(qr_y_textos)

            story.append(KeepTogether(footer_elements))

            if not es_ultima_pagina:
                story.append(PageBreak())

        doc.build(story, canvasmaker=NumberedCanvas)
        pdf_data = buffer.getvalue()
        buffer.close()

        return pdf_data

    def _get_logo_empresa(self):
        """Retorna el logo de la empresa"""
        company = self.company_id

        if company.logo:
            try:
                logo_data = BytesIO(base64.b64decode(company.logo))
                logo = Image(logo_data, width=35 * mm, height=35 * mm)
                return logo
            except:
                return Paragraph("", getSampleStyleSheet()['Normal'])

        return Paragraph("LOGO", getSampleStyleSheet()['Normal'])

    def _get_datos_empresa(self):
        """Retorna datos de la empresa"""
        company = self.company_id

        datos_html = f"""
        <para align=center>
        <b>{company.name}</b><br/>
        <b>CASA MATRIZ</b><br/>
        No. Punto de Venta {company.siat_codigo_punto_venta or 0}<br/>
        {company.street or 'Sin dirección'}<br/>
        Tel: {company.phone or 'Sin teléfono'}<br/>
        <b>{company.city or 'CIUDAD'}</b>
        </para>
        """

        style = ParagraphStyle(
            'DatosEmpresa',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=7,
            alignment=TA_CENTER
        )

        return Paragraph(datos_html, style)

    def _get_datos_factura_box(self):
        cuf = self.siat_cuf or ''
        cuf_lines = []
        if cuf:
            for i in range(0, len(cuf), 22):
                cuf_lines.append(cuf[i:i + 22])

        cuf_display = '<br/>'.join(cuf_lines) if cuf_lines else 'Sin CUF'

        datos_html = f"""
        <para align=center>
        <b>NIT</b> {self.company_id.vat}<br/>
        <b>FACTURA N°</b> {self.siat_numero_factura}<br/>
        <b>COD. AUTORIZACION</b><br/>
        <font size=6>{cuf_display}</font>
        </para>
        """

        style = ParagraphStyle(
            'DatosFactura',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=7,
            alignment=TA_CENTER,
            borderWidth=1,
            borderColor=colors.black,
            borderPadding=6,
            leftIndent=4,
            rightIndent=4
        )

        data = [[Paragraph(datos_html, style)]]
        table = Table(data, colWidths=[60 * mm])
        table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))

        return table

    def _get_datos_cliente(self):
        partner = self.partner_id
        fecha_emision = self.invoice_date.strftime('%d/%m/%Y %I:%M %p') if self.invoice_date else ''

        style_small = ParagraphStyle('small', parent=getSampleStyleSheet()['Normal'], fontSize=8)

        return [
            [
                Paragraph(f"<b>Fecha:</b>", style_small),
                Paragraph(fecha_emision, style_small),
                Paragraph(f"<b>NIT/CI/CEX:</b>", style_small),
            ],
            [
                Paragraph(f"<b>Razón Social:</b>", style_small),
                Paragraph(partner.name, style_small),
                Paragraph(partner.vat or '', style_small),
            ],
            [
                Paragraph("", style_small),
                Paragraph("", style_small),
                Paragraph(f"<b>Cod. Cliente:</b> {partner.codigo_cliente or partner.vat or f'C{partner.id}'}",
                          style_small),
            ]
        ]

    def _get_tabla_detalle_bloque(self, productos_bloque):
        """Genera tabla de detalle - PRECIOS SIEMPRE EN BOLIVIANOS"""
        data = [
            [
                Paragraph('<b>CÓDIGO<br/>PRODUCTO</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>CANT.</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>U.M.</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>DESCRIPCIÓN</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>PRECIO<br/>UNITARIO<br/>(Bs.)</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>DESC.</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
                Paragraph('<b>SUBTOTAL<br/>(Bs.)</b>',
                          ParagraphStyle('header', fontSize=8, alignment=TA_CENTER)),
            ]
        ]

        style_cell = ParagraphStyle('cell', fontSize=8, alignment=TA_LEFT)
        style_number = ParagraphStyle('number', fontSize=8, alignment=TA_RIGHT)

        for line in productos_bloque:
            product = line.product_id
            codigo = product.default_code or f'P-{product.id}'
            unidad = product.product_tmpl_id.siat_codigo_unidad_medida or 58

            if self.siat_es_moneda_extranjera:
                precio_unitario_bob = line.price_unit * self.siat_tipo_cambio
                subtotal_bob = line.quantity * precio_unitario_bob

                _logger.info(
                    f"[PDF] Producto: {product.name} - "
                    f"{line.price_unit:.2f} {self.currency_id.name} × {self.siat_tipo_cambio:.2f} = "
                    f"{precio_unitario_bob:.2f} Bs."
                )
            else:
                precio_unitario_bob = line.price_unit
                subtotal_bob = line.quantity * precio_unitario_bob

            descuento = line.discount if hasattr(line, 'discount') else 0

            data.append([
                Paragraph(codigo[:15], style_cell),
                Paragraph(f"{line.quantity:.1f}", style_number),
                Paragraph(str(unidad), style_cell),
                Paragraph(line.name or product.name, style_cell),
                Paragraph(self._formatear_numero(precio_unitario_bob, 2), style_number),
                Paragraph(f"{descuento:.1f}", style_number),
                Paragraph(self._formatear_numero(subtotal_bob, 2), style_number),
            ])

        table = Table(data,
                      colWidths=[23 * mm, 16 * mm, 14 * mm, 63 * mm, 24 * mm, 16 * mm, 24 * mm])

        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7BA3CC')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
        ]))

        return table

    def _get_tabla_totales(self):
        """Tabla de totales - Muestra USD y BOB CON FORMATO DE COMAS"""
        es_moneda_extranjera = self.siat_es_moneda_extranjera
        
        # Obtener descuento global
        descuento_global = self._get_descuento_global_amount()

        style_tot = ParagraphStyle('tot', fontSize=8, alignment=TA_RIGHT)
        style_tot_bold = ParagraphStyle('tot_bold', fontSize=9, alignment=TA_RIGHT, fontName='Helvetica-Bold')

        data = []

        if es_moneda_extranjera:
            monto_extranjero = self.amount_total
            # Calcular subtotal sin descuento (suma de líneas excluyendo global_discount)
            subtotal_bob = self.siat_monto_total_bolivianos + descuento_global
            monto_bob = self.siat_monto_total_bolivianos
            moneda_codigo = self.currency_id.name
            tipo_cambio = self.siat_tipo_cambio

            _logger.info("=" * 80)
            _logger.info(f"[PDF TOTALES] Factura en {moneda_codigo}")
            _logger.info(f"  Subtotal {moneda_codigo}: {monto_extranjero:.2f}")
            _logger.info(f"  Subtotal Bs.: {subtotal_bob:.2f}")
            _logger.info(f"  Descuento Bs.: {descuento_global:.2f}")
            _logger.info(f"  Total Bs.: {monto_bob:.2f}")
            _logger.info(f"  Tipo de Cambio: {tipo_cambio:.2f}")
            _logger.info("=" * 80)

            data = [
                ['', Paragraph(f'<b>SUBTOTAL {moneda_codigo}</b>', style_tot),
                 Paragraph(self._formatear_numero(monto_extranjero, 2), style_tot)],

                ['', Paragraph('<b>SUBTOTAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(subtotal_bob, 2), style_tot)],

                ['', '', ''],

                ['', Paragraph('<b>DESCUENTO Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(descuento_global, 2), style_tot)],
                ['', Paragraph('<b>TOTAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(monto_bob, 2), style_tot)],
                ['', Paragraph('<b>MONTO GIFT CARD Bs.</b>', style_tot),
                 Paragraph('0.00', style_tot)],
                ['', Paragraph('<b>MONTO A PAGAR Bs.</b>', style_tot_bold),
                 Paragraph(f'<b>{self._formatear_numero(monto_bob, 2)}</b>', style_tot_bold)],
                ['', Paragraph('<b>IMPORTE BASE CRÉDITO FISCAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(monto_bob, 2), style_tot)],
            ]

        else:
            # Calcular subtotal (suma de líneas sin descuento global)
            subtotal_bob = self.amount_total + descuento_global
            monto_total = self.amount_total

            _logger.info("=" * 80)
            _logger.info(f"[PDF TOTALES] Factura en BOB")
            _logger.info(f"  Subtotal Bs.: {subtotal_bob:.2f}")
            _logger.info(f"  Descuento Bs.: {descuento_global:.2f}")
            _logger.info(f"  Total Bs.: {monto_total:.2f}")
            _logger.info("=" * 80)

            data = [
                ['', Paragraph('<b>SUBTOTAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(subtotal_bob, 2), style_tot)],
                ['', Paragraph('<b>DESCUENTO Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(descuento_global, 2), style_tot)],
                ['', Paragraph('<b>TOTAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(monto_total, 2), style_tot)],
                ['', Paragraph('<b>MONTO GIFT CARD Bs.</b>', style_tot),
                 Paragraph('0.00', style_tot)],
                ['', Paragraph('<b>MONTO A PAGAR Bs.</b>', style_tot_bold),
                 Paragraph(f'<b>{self._formatear_numero(monto_total, 2)}</b>', style_tot_bold)],
                ['', Paragraph('<b>IMPORTE BASE CRÉDITO FISCAL Bs.</b>', style_tot),
                 Paragraph(self._formatear_numero(monto_total, 2), style_tot)],
            ]

        table = Table(data, colWidths=[85 * mm, 65 * mm, 35 * mm])
        table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LINEABOVE', (1, -2), (-1, -2), 1.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))

        return table

    def _get_qr_y_textos_layout(self):

        leyenda_html = f"""
        <para align=left fontSize=6>
        ESTA FACTURA CONTRIBUYE AL DESARROLLO DEL PAÍS, EL USO ILÍCITO SERÁ SANCIONADO PENALMENTE DE ACUERDO A LEY<br/><br/>
        <b>{self._obtener_leyenda_aleatoria_invoice()}</b><br/><br/>
        Este documento es la Representación Gráfica de un Documento Fiscal Digital emitido en una modalidad de facturación en línea
        </para>
        """

        style_pie = ParagraphStyle(
            'PiePagina',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=6,
            alignment=TA_LEFT
        )

        textos_pie = Paragraph(leyenda_html, style_pie)

        qr_image = self._generar_qr_code()

        if qr_image:
            layout_data = [[qr_image, textos_pie]]
            layout_table = Table(layout_data, colWidths=[35 * mm, 150 * mm])
            layout_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ]))
            return layout_table
        else:
            return textos_pie

    def _get_siat_qr_base_url(self):
        """Obtiene la URL base del QR desde la configuración SIAT"""
        siat_config = self.env['alpha.siat.config'].search([], limit=1)
        if siat_config and siat_config.url_qr:
            return siat_config.url_qr
        # Valor por defecto si no hay configuración
        return 'https://pilotosiat.impuestos.gob.bo/consulta/QR?'

    def _generar_qr_code(self):
        try:
            if not self.siat_cuf or not self.siat_numero_factura:
                _logger.warning("No hay CUF o número de factura para generar QR")
                return None

            company = self.company_id

            qr_base_url = self._get_siat_qr_base_url()

            qr_url = (
                f"{qr_base_url}"
                f"nit={company.vat or ''}&"
                f"cuf={self.siat_cuf}&"
                f"numero={self.siat_numero_factura}&"
                f"t=1"
            )

            _logger.info("=" * 100)
            _logger.info("[PDF QR] GENERANDO QR PARA FACTURA")
            _logger.info(f"  URL Base QR: {qr_base_url}")
            _logger.info(f"  NIT Emisor: {company.vat}")
            _logger.info(f"  CUF: {self.siat_cuf}")
            _logger.info(f"  Número Factura: {self.siat_numero_factura}")
            _logger.info(f"  URL QR: {qr_url}")
            _logger.info("=" * 100)

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=3,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)

            qr_img = qr.make_image(fill_color="black", back_color="white")

            img_buffer = BytesIO()
            qr_img.save(img_buffer, format='PNG')
            img_buffer.seek(0)

            _logger.info("QR generado exitosamente")

            return Image(img_buffer, width=30 * mm, height=30 * mm)
        except Exception as e:
            _logger.error(f"Error generando QR: {e}")
            return None

    def _convertir_monto_a_letras(self, monto):
        """Convierte monto a letras - SIEMPRE EN BOLIVIANOS"""
        try:
            # Siempre usar el monto en bolivianos
            if self.siat_es_moneda_extranjera:
                monto_bob = self.siat_monto_total_bolivianos
            else:
                monto_bob = self.amount_total

            entero = int(monto_bob)
            decimal = int(round((monto_bob - entero) * 100))

            # Conversión básica a texto
            if entero == 0:
                texto = "Cero"
            elif entero < 10:
                unidades = ['Cero', 'Uno', 'Dos', 'Tres', 'Cuatro', 'Cinco',
                            'Seis', 'Siete', 'Ocho', 'Nueve']
                texto = unidades[entero]
            elif entero < 20:
                especiales = ['Diez', 'Once', 'Doce', 'Trece', 'Catorce', 'Quince',
                              'Dieciséis', 'Diecisiete', 'Dieciocho', 'Diecinueve']
                texto = especiales[entero - 10]
            elif entero < 100:
                decenas = ['', '', 'Veinte', 'Treinta', 'Cuarenta', 'Cincuenta',
                           'Sesenta', 'Setenta', 'Ochenta', 'Noventa']
                unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco',
                            'seis', 'siete', 'ocho', 'nueve']
                d = entero // 10
                u = entero % 10
                if u == 0:
                    texto = decenas[d]
                else:
                    texto = f"{decenas[d]} y {unidades[u]}"
            elif entero < 1000:
                texto = self._convertir_centenas(entero)
            else:
                # Para miles
                miles = entero // 1000
                resto = entero % 1000
                if miles == 1:
                    texto_miles = "mil"
                else:
                    texto_miles = f"{self._convertir_centenas(miles)} mil"

                if resto > 0:
                    texto = f"{texto_miles} {self._convertir_centenas(resto)}"
                else:
                    texto = texto_miles

            return f"{texto.title()} {decimal:02d}/100 Bolivianos"

        except Exception as e:
            _logger.error(f"Error convirtiendo monto: {str(e)}")
            monto_final = self.siat_monto_total_bolivianos if self.siat_es_moneda_extranjera else self.amount_total
            return f"{monto_final:.2f} Bolivianos"

    def _convertir_centenas(self, numero):
        """Convierte números de 0-999 a texto"""
        if numero == 0:
            return ""
        elif numero < 20:
            unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve',
                        'diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete', 'dieciocho',
                        'diecinueve']
            return unidades[numero]
        elif numero < 100:
            decenas = ['', '', 'veinte', 'treinta', 'cuarenta', 'cincuenta',
                       'sesenta', 'setenta', 'ochenta', 'noventa']
            unidades = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco',
                        'seis', 'siete', 'ocho', 'nueve']
            d = numero // 10
            u = numero % 10
            if u == 0:
                return decenas[d]
            else:
                return f"{decenas[d]} y {unidades[u]}"
        else:
            centenas = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos',
                        'seiscientos', 'setecientos', 'ochocientos', 'novecientos']
            c = numero // 100
            resto = numero % 100

            if numero == 100:
                return "cien"
            elif resto == 0:
                return centenas[c]
            else:
                return f"{centenas[c]} {self._convertir_centenas(resto)}"

    def _formatear_numero(self, numero, decimales=2):

        try:
            if decimales == 2:
                return f"{numero:,.2f}"
            elif decimales == 3:
                return f"{numero:,.3f}"
            else:
                return f"{numero:,.{decimales}f}"
        except:
            return str(numero)