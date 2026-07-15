# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from lxml import etree
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    siat_xml_factura = fields.Text(
        string='XML Factura SIAT',
        readonly=True,
        copy=False,
        help='XML de la factura enviada a SIAT'
    )
    siat_cuf = fields.Char(
        string='CUF',
        readonly=True,
        copy=False,
        help='Código Único de Factura generado por SIAT'
    )
    siat_numero_factura = fields.Integer(
        string='Número Factura SIAT',
        readonly=True,
        copy=False,
        help='Número de factura asignado para SIAT'
    )
    siat_estado_envio = fields.Char(
        string='Estado Envío SIAT',
        readonly=True,
        copy=False,
        help='Estado de la respuesta de SIAT'
    )
    siat_codigo_recepcion = fields.Char(
        string='Código Recepción SIAT',
        readonly=True,
        copy=False,
        help='Código de recepción devuelto por SIAT'
    )
    siat_mensajes_envio = fields.Text(
        string='Mensajes SIAT',
        readonly=True,
        copy=False,
        help='Mensajes devueltos por SIAT'
    )
    siat_fecha_envio = fields.Datetime(
        string='Fecha Envío SIAT',
        readonly=True,
        copy=False,
        help='Fecha y hora de envío a SIAT'
    )
    siat_facturado = fields.Boolean(
        string='Facturado en SIAT',
        readonly=True,
        copy=False,
        compute='_compute_siat_facturado',
        store=True,
        help='Indica si la factura fue enviada y aceptada por SIAT'
    )
    siat_anulado = fields.Boolean(
        string='Anulado en SIAT',
        readonly=True,
        copy=False,
        default=False,
        help='Indica si la factura fue anulada en SIAT'
    )
    siat_fecha_anulacion = fields.Datetime(
        string='Fecha Anulación SIAT',
        readonly=True,
        copy=False,
        help='Fecha y hora en que se anuló la factura en SIAT'
    )
    siat_motivo_anulacion = fields.Integer(
        string='Código Motivo Anulación',
        readonly=True,
        copy=False,
        help='Código del motivo de anulación (1=Genérico)'
    )
    siat_es_moneda_extranjera = fields.Boolean(
        string='Es Moneda Extranjera',
        compute='_compute_siat_es_moneda_extranjera',
        store=True,
        help='Indica si la factura es en moneda diferente a BOB'
    )
    siat_tipo_cambio = fields.Float(
        string='Tipo de Cambio',
        digits=(12, 2),
        compute='_compute_siat_tipo_cambio',
        store=True,
        readonly=True,
        help='Tipo de cambio usado en la transacción (BOB per Unit)'
    )
    siat_monto_total_moneda = fields.Monetary(
        string='Monto Total en Moneda Extranjera',
        currency_field='currency_id',
        compute='_compute_siat_monto_total_moneda',
        store=True,
        readonly=True,
        help='Monto total en la moneda extranjera (USD, EUR, etc.)'
    )
    siat_monto_total_bolivianos = fields.Float(
        string='Monto Total en Bolivianos',
        digits=(16, 2),
        compute='_compute_siat_monto_total_bolivianos',
        store=True,
        readonly=True,
        help='Monto total convertido a Bolivianos'
    )
    siat_metodo_pago_id = fields.Many2one(
        'alpha.siat.tipo.metodo.pago',
        string='Método de Pago SIAT',
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help='Método de pago para facturación SIAT',
        tracking=True,
        default=lambda self: self._default_metodo_pago()
    )

    siat_emails_destinatarios = fields.Char(
        string='Enviar factura a',
        help='Correos electrónicos separados por comas para enviar el PDF de la factura',
        tracking=True
    )

    @api.model
    def _default_metodo_pago(self):
        """Retorna método de pago por defecto (Efectivo)"""
        MetodoPago = self.env['alpha.siat.tipo.metodo.pago']
        company = self.env.company
        # Buscar EFECTIVO (código 1)
        metodo = MetodoPago.search([
            ('company_id', '=', company.id),
            ('codigo_clasificador', '=', 1),
            ('active', '=', True)
        ], limit=1)
        return metodo.id if metodo else False

    @api.depends('currency_id')
    def _compute_siat_es_moneda_extranjera(self):
        """Determina si la factura es en moneda extranjera"""
        for move in self:
            if move.currency_id and move.currency_id.name != 'BOB':
                move.siat_es_moneda_extranjera = True
            else:
                move.siat_es_moneda_extranjera = False

    @api.depends('currency_id', 'invoice_date', 'date')
    def _compute_siat_tipo_cambio(self):
        """
        Obtiene el tipo de cambio de la transacción.
        Usa inverse_company_rate que es "BOB per Unit"
        """
        for move in self:
            if not move.siat_es_moneda_extranjera:
                move.siat_tipo_cambio = 1.00
                continue

            fecha = move.invoice_date or move.date or fields.Date.today()
            company = move.company_id or self.env.company

            try:
                # Buscar el rate de la moneda para la fecha
                CurrencyRate = self.env['res.currency.rate']
                rate_record = CurrencyRate.search([
                    ('currency_id', '=', move.currency_id.id),
                    ('company_id', 'in', [company.id, False]),
                    ('name', '<=', fecha)
                ], order='name desc', limit=1)

                if rate_record:
                    # inverse_company_rate = BOB per Unit (6.96)
                    # Este campo se calcula como: 1.0 / company_rate
                    tipo_cambio = rate_record.inverse_company_rate
                    move.siat_tipo_cambio = round(tipo_cambio, 2)

                    _logger.info(
                        f"Tipo de cambio para {move.currency_id.name}: "
                        f"rate={rate_record.rate:.6f}, "
                        f"company_rate={rate_record.company_rate:.6f}, "
                        f"inverse_company_rate={rate_record.inverse_company_rate:.6f} → "
                        f"SIAT: {move.siat_tipo_cambio:.2f} BOB per Unit"
                    )
                else:
                    _logger.warning(f"No se encontró rate para {move.currency_id.name}")
                    move.siat_tipo_cambio = 1.00

            except Exception as e:
                _logger.error(f"Error calculando tipo de cambio: {str(e)}")
                move.siat_tipo_cambio = 1.00

    @api.depends('amount_total', 'currency_id')
    def _compute_siat_monto_total_moneda(self):
        """Calcula el monto total en moneda extranjera"""
        for move in self:
            if move.siat_es_moneda_extranjera:
                move.siat_monto_total_moneda = move.amount_total
            else:
                move.siat_monto_total_moneda = 0.0

    @api.depends('invoice_line_ids', 'invoice_line_ids.price_unit', 'invoice_line_ids.quantity',
                 'currency_id', 'siat_tipo_cambio', 'invoice_date', 'date')
    def _compute_siat_monto_total_bolivianos(self):
        """Calcula el monto total convertido a Bolivianos con precisión Decimal"""
        for move in self:
            if not move.siat_es_moneda_extranjera:
                move.siat_monto_total_bolivianos = move.amount_total
            else:
                monto_total_bob_decimal = Decimal('0.0')

                for line in move.invoice_line_ids:
                    if line.product_id:
                        product_tmpl = line.product_id.product_tmpl_id
                        if product_tmpl.siat_homologado:
                            precio_unit_decimal = Decimal(str(line.price_unit))
                            tipo_cambio_decimal = Decimal(str(move.siat_tipo_cambio))
                            cantidad_decimal = Decimal(str(line.quantity))

                            precio_bob_decimal = precio_unit_decimal * tipo_cambio_decimal
                            precio_bob_decimal = precio_bob_decimal.quantize(
                                Decimal('0.01'),
                                rounding=ROUND_HALF_UP
                            )

                            subtotal_decimal = cantidad_decimal * precio_bob_decimal

                            subtotal_bob_decimal = subtotal_decimal.quantize(
                                Decimal('0.01'),
                                rounding=ROUND_HALF_UP
                            )

                            monto_total_bob_decimal += subtotal_bob_decimal

                move.siat_monto_total_bolivianos = float(monto_total_bob_decimal)

                _logger.info(
                    f"Monto Total Bolivianos (Decimal): {move.amount_total:.2f} {move.currency_id.name} "
                    f"→ {float(monto_total_bob_decimal):.2f} BOB [CALCULADO CON DECIMAL]"
                )

    @api.depends('siat_estado_envio', 'siat_codigo_recepcion')
    def _compute_siat_facturado(self):
        """Calcula si la factura fue aceptada por SIAT"""
        for move in self:
            move.siat_facturado = bool(
                move.siat_estado_envio == '908' and
                move.siat_codigo_recepcion
            )

    def _es_modalidad_electronica(self):
        """Retorna True si la configuracion SIAT es modalidad Electronica En Linea"""
        config = self.company_id.siat_config_id
        return config and config.modalidad == '1'

    def _firmar_xml_electronico(self, xml_string, config):
        """
        Envia el XML sin firmar al microservicio externo de firma digital.
        Retorna el XML firmado (con bloque <Signature> incluido).
        """
        self.ensure_one()
        import requests

        url_firma = config.url_firma
        if not url_firma:
            raise ValidationError(
                "URL DEL MICROSERVICIO DE FIRMA NO CONFIGURADA\n\n"
                "La modalidad 'Electronica En Linea' requiere un microservicio de firma digital.\n\n"
                "Configure la URL en: Facturacion > Configuracion > SIAT > URL Microservicio de Firma"
            )

        _logger.info("=" * 80)
        _logger.info(f"[FIRMA] Enviando XML al microservicio: {url_firma}")
        _logger.info(f"[FIRMA] Tamano XML: {len(xml_string)} chars")
        _logger.info("[FIRMA] XML a firmar:")
        _logger.info(xml_string)
        _logger.info("=" * 80)

        try:
            response = requests.post(
                url_firma,
                data=xml_string.encode('utf-8'),
                headers={'Content-Type': 'application/xml'},
                timeout=30
            )

            _logger.info("=" * 80)
            _logger.info(f"[FIRMA] HTTP Status: {response.status_code}")
            _logger.info(f"[FIRMA] Respuesta ({len(response.text)} chars):")
            _logger.info(response.text)
            _logger.info("=" * 80)

            response.raise_for_status()

            xml_firmado = response.text
            if not xml_firmado or 'Signature' not in xml_firmado:
                raise ValidationError(
                    "RESPUESTA INVALIDA DEL MICROSERVICIO DE FIRMA\n\n"
                    "El microservicio no devolvio un XML firmado valido.\n"
                    f"Respuesta recibida: {xml_firmado[:200] if xml_firmado else '(vacia)'}"
                )

            _logger.info("\u2713 [FIRMA] XML firmado correctamente")
            return xml_firmado

        except requests.exceptions.ConnectionError:
            raise ValidationError(
                f"NO SE PUDO CONECTAR AL MICROSERVICIO DE FIRMA\n\n"
                f"URL: {url_firma}\n\n"
                f"Verifique que el microservicio este activo y accesible."
            )
        except requests.exceptions.Timeout:
            raise ValidationError(
                f"TIEMPO DE ESPERA AGOTADO AL FIRMAR\n\n"
                f"El microservicio de firma tardo demasiado en responder.\n"
                f"URL: {url_firma}"
            )
        except requests.exceptions.HTTPError as e:
            raise ValidationError(
                f"ERROR EN EL MICROSERVICIO DE FIRMA\n\n"
                f"Codigo HTTP: {response.status_code}\n"
                f"Detalle: {str(e)}"
            )
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Error inesperado al firmar XML: {str(e)}")

    def _es_linea_descuento_global(self, line):
        """Verifica si una línea es el producto de descuento global"""
        return line.product_id and line.product_id.default_code == 'global_discount'

    def _get_descuento_global_amount(self):
        """
        Obtiene el monto del descuento global (producto con default_code='global_discount').
        El valor en Odoo es negativo, se retorna como positivo en BOB.
        """
        self.ensure_one()
        for line in self.invoice_line_ids:
            if self._es_linea_descuento_global(line):
                # price_subtotal es negativo, lo convertimos a positivo
                monto = abs(line.price_subtotal)
                
                # Si es moneda extranjera, convertir a BOB
                if self.siat_es_moneda_extranjera:
                    monto_decimal = Decimal(str(monto))
                    tipo_cambio_decimal = Decimal(str(self.siat_tipo_cambio))
                    monto_bob = monto_decimal * tipo_cambio_decimal
                    return float(monto_bob.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                
                return round(monto, 2)
        
        return 0.0

    def action_enviar_factura_siat(self):
        """Acción para enviar la factura a SIAT desde Invoicing"""
        self.ensure_one()

        _logger.info("=" * 100)
        _logger.info(f"ENVIAR FACTURA A SIAT - Factura: {self.name}")
        _logger.info(f"Moneda: {self.currency_id.name}")
        _logger.info(f"Es moneda extranjera: {self.siat_es_moneda_extranjera}")
        if self.siat_es_moneda_extranjera:
            _logger.info(f"Tipo de Cambio: {self.siat_tipo_cambio}")
            _logger.info(f"Monto en {self.currency_id.name}: {self.siat_monto_total_moneda}")
            _logger.info(f"Monto en BOB: {self.siat_monto_total_bolivianos}")
        _logger.info("=" * 100)

        # Validaciones previas
        if self.move_type not in ['out_invoice', 'out_refund']:
            raise UserError(
                "TIPO DE DOCUMENTO INVALIDO\n\n"
                "Solo se pueden enviar a SIAT:\n"
                "• Facturas de cliente (out_invoice)\n"
                "• Notas de crédito (out_refund)\n\n"
                f"Este documento es de tipo: {self.move_type}"
            )

        if self.state != 'posted':
            raise UserError(
                "FACTURA NO CONFIRMADA\n\n"
                "La factura debe estar confirmada (estado 'Asentado')\n"
                "antes de enviarla a SIAT.\n\n"
                "Por favor, confirme la factura primero."
            )

        if self.siat_facturado:
            raise UserError(
                "FACTURA YA ENVIADA A SIAT\n\n"
                f"Esta factura ya fue enviada y aceptada por SIAT.\n"
                f"CUF: {self.siat_cuf}\n"
                f"Código de Recepción: {self.siat_codigo_recepcion}\n\n"
                "No se puede enviar nuevamente."
            )

        # Validar requisitos SIAT
        try:
            self._validar_requisitos_siat_invoice()
        except Exception as e:
            _logger.error(f"Error en validaciones: {str(e)}", exc_info=True)
            raise

        try:
            xml_generado = self._generar_xml_factura_siat_invoice()
            if xml_generado:
                _logger.info("✓ Factura enviada exitosamente a SIAT")
                return True
        except Exception as e:
            _logger.error(f"Error generando factura SIAT: {str(e)}", exc_info=True)
            raise

    def _validar_requisitos_siat_invoice(self):
        """Valida que la factura tenga todos los requisitos para SIAT"""
        self.ensure_one()

        _logger.info("Validando requisitos SIAT para factura...")

        # 1. Validar cliente
        if not self.partner_id:
            raise UserError("CLIENTE NO ESPECIFICADO\n\nLa factura debe tener un cliente asignado.")

        if not self.partner_id.vat:
            raise UserError(
                f"NIT/CI DEL CLIENTE NO CONFIGURADO\n\n"
                f"El cliente '{self.partner_id.name}' no tiene NIT/CI.\n\n"
                f"Configure el NIT/CI en: Contactos > {{cliente}} > Campo 'NIT/Identificación Fiscal'"
            )

        # 2. Validar compañía
        if not self.company_id.vat:
            raise UserError(
                f"NIT DE LA EMPRESA NO CONFIGURADO\n\n"
                f"La empresa '{self.company_id.name}' no tiene NIT.\n\n"
                f"Configure el NIT en: Ajustes > Empresas > {{empresa}} > NIT"
            )

        # 3. Validar configuración SIAT
        config = self.company_id.siat_config_id
        if not config:
            raise UserError(
                f"CONFIGURACION SIAT NO ENCONTRADA\n\n"
                f"La empresa '{self.company_id.name}' no tiene configuración SIAT.\n\n"
                f"Configure SIAT en: Facturación > Configuración > SIAT"
            )

        # 4. Validar moneda configurada
        if not self.currency_id:
            raise UserError("MONEDA NO CONFIGURADA\n\nLa factura debe tener una moneda asignada.")

        # 5. Validar método de pago
        if not self.siat_metodo_pago_id:
            raise UserError(
                "MÉTODO DE PAGO NO SELECCIONADO\n\n"
                "Debe seleccionar un método de pago SIAT para la factura.\n\n"
                "Si no ve opciones disponibles, sincronice los métodos de pago en:\n"
                "Facturación > Configuración > SIAT > Sincronizar Parámetros"
            )

        # 6. Validar tipo de cambio (solo para monedas extranjeras)
        if self.siat_es_moneda_extranjera:
            if not self.siat_tipo_cambio or self.siat_tipo_cambio <= 0:
                raise UserError(
                    f"TIPO DE CAMBIO NO DISPONIBLE\n\n"
                    f"No se pudo obtener el tipo de cambio para {self.currency_id.name}.\n\n"
                    f"Verifique que exista un tipo de cambio configurado para hoy."
                )

        # 7. Validar productos homologados (excluyendo línea de descuento global)
        productos_sin_homologar = []
        for line in self.invoice_line_ids:
            if line.product_id and not self._es_linea_descuento_global(line):
                product_tmpl = line.product_id.product_tmpl_id
                if not product_tmpl.siat_homologado:
                    productos_sin_homologar.append(line.product_id.name)

        if productos_sin_homologar:
            raise UserError(
                "PRODUCTOS NO HOMOLOGADOS\n\n"
                "Los siguientes productos no están homologados con SIAT:\n\n" +
                "\n".join(f"• {p}" for p in productos_sin_homologar) +
                "\n\nDebe homologar estos productos antes de facturar.\n"
                "Vaya a: Productos > {producto} > Pestaña SIAT"
            )

        # 8. Validar CUFD
        cufd_record = self._obtener_cufd_valido_invoice()
        if not cufd_record:
            raise UserError(
                "NO HAY CUFD VALIDO\n\n"
                "No se puede generar la factura sin un CUFD vigente.\n\n"
                "Sincronice el CUFD en: Facturación > Configuración > SIAT > Sincronizar CUFD"
            )

        # 9. Validar que tenga líneas
        if not self.invoice_line_ids:
            raise UserError("FACTURA SIN LINEAS\n\nLa factura debe tener al menos una línea de producto.")

        _logger.info("✓ Todas las validaciones pasaron correctamente")

    def _obtener_cufd_valido_invoice(self):
        """Obtiene un CUFD válido para la factura"""
        cufd_model = self.env['alpha.siat.cufd']
        cufd_valido = cufd_model.search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'valid')
        ], limit=1, order='fecha_vigencia desc')

        if cufd_valido:
            now_utc = datetime.now(timezone.utc)
            bolivia_tz = timezone(timedelta(hours=-4))
            now_bolivia = now_utc.astimezone(bolivia_tz)

            fecha_vigencia = cufd_valido.fecha_vigencia
            if isinstance(fecha_vigencia, str):
                fecha_vigencia = datetime.fromisoformat(fecha_vigencia.replace('Z', '+00:00'))
            if not fecha_vigencia.tzinfo:
                fecha_vigencia = fecha_vigencia.replace(tzinfo=timezone.utc)

            fecha_vigencia_bolivia = fecha_vigencia.astimezone(bolivia_tz)

            if now_bolivia < fecha_vigencia_bolivia:
                _logger.info(f"✓ CUFD válido encontrado: {cufd_valido.cufd[:20]}...")
                return cufd_valido
            else:
                cufd_valido.write({'state': 'expired'})

        _logger.error("✗ NO HAY CUFD VALIDO DISPONIBLE")
        return None

    def _obtener_numero_factura_invoice(self):
        """Obtiene el siguiente número de factura para SIAT"""
        self.ensure_one()

        ultima_factura = self.search([
            ('company_id', '=', self.company_id.id),
            ('siat_numero_factura', '!=', False),
            ('move_type', '=', 'out_invoice')
        ], order='siat_numero_factura desc', limit=1)

        if ultima_factura:
            siguiente_numero = ultima_factura.siat_numero_factura + 1
        else:
            siguiente_numero = 1

        _logger.info(f"Número de factura SIAT asignado: {siguiente_numero}")
        return siguiente_numero

    def _generar_cuf_dinamico_invoice(self, numero_factura, fecha_hora_bolivia):
        """Genera el CUF para la factura"""
        self.ensure_one()

        try:
            cuf_generator = self.env['alpha.siat.cuf.generator']
            resultado = cuf_generator.generar_cuf(
                company_id=self.company_id.id,
                numero_factura=numero_factura,
                fecha_hora_emision=fecha_hora_bolivia
            )

            if resultado and resultado.get('cuf'):
                _logger.info(f"CUF generado: {resultado['cuf']}")
                return resultado
            else:
                raise ValidationError("No se pudo generar el CUF")

        except Exception as e:
            _logger.error(f"Error generando CUF: {str(e)}", exc_info=True)
            raise ValidationError(f"Error al generar CUF: {str(e)}")

    def _obtener_leyenda_aleatoria_invoice(self):
        """Obtiene una leyenda aleatoria para la factura"""
        import random
        leyendas = [
            "Ley N° 453: El proveedor debe brindar atención sin discriminación, con respeto, calidez y cordialidad a los usuarios y consumidores.",
            "Ley N° 453: Tienes derecho a recibir información sobre las características y contenidos de los servicios que utilices.",
            "Ley N° 453: Puedes acceder a la reclamación cuando tus derechos han sido vulnerados.",
            "Ley N° 453: El proveedor debe respetar los términos, plazos y condiciones ofrecidas o convenidas.",
            "Ley N° 453: Tienes derecho a que en caso de reposición, cambio o devolución, sea de forma gratuita."
        ]
        return random.choice(leyendas)

    def _generar_xml_factura_siat_invoice(self):
        self.ensure_one()

        _logger.info("=" * 100)
        _logger.info(f"GENERANDO XML FACTURA SIAT - Invoice: {self.name}")
        _logger.info(f"Moneda: {self.currency_id.name}")
        if self.siat_es_moneda_extranjera:
            _logger.info(f"Tipo de Cambio: {self.siat_tipo_cambio}")
            _logger.info(f"Monto en {self.currency_id.name}: {self.siat_monto_total_moneda}")
            _logger.info(f"Monto en BOB: {self.siat_monto_total_bolivianos}")
        _logger.info("=" * 100)

        try:
            company = self.company_id
            partner = self.partner_id

            cufd_record = self._obtener_cufd_valido_invoice()
            if not cufd_record:
                raise UserError("No hay CUFD válido disponible")

            numero_factura = self._obtener_numero_factura_invoice()

            # Generar fecha/hora
            ahora_utc = datetime.now(timezone.utc)
            bolivia_tz = timezone(timedelta(hours=-4))
            ahora_bolivia = ahora_utc.astimezone(bolivia_tz)

            # Generar CUF
            cuf_resultado = self._generar_cuf_dinamico_invoice(numero_factura, ahora_bolivia)
            cuf_generado = cuf_resultado['cuf']

            leyenda = self._obtener_leyenda_aleatoria_invoice()

            # Obtener descuento global
            descuento_global = self._get_descuento_global_amount()
            if descuento_global > 0:
                _logger.info(f"Descuento global detectado: {descuento_global:.2f} BOB")

            # ================================================================
            # CREAR XML
            # ================================================================
            etree.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
            es_electronica = self._es_modalidad_electronica()
            nombre_elemento_raiz = (
                'facturaElectronicaCompraVenta' if es_electronica
                else 'facturaComputarizadaCompraVenta'
            )
            xsd_referencia = (
                'facturaElectronicaCompraVenta.xsd' if es_electronica
                else 'facturaComputarizadaCompraVenta.xsd'
            )
            root = etree.Element(nombre_elemento_raiz)
            root.set('{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation',
                     xsd_referencia)

            cabecera = etree.SubElement(root, 'cabecera')

            # Datos del emisor
            etree.SubElement(cabecera, 'nitEmisor').text = str(company.vat)
            etree.SubElement(cabecera, 'razonSocialEmisor').text = company.name[:200]
            etree.SubElement(cabecera, 'municipio').text = 'Nuestra Senora de La Paz'
            etree.SubElement(cabecera, 'telefono').text = company.phone[:25] if company.phone else '0000000'
            etree.SubElement(cabecera, 'numeroFactura').text = str(numero_factura)
            etree.SubElement(cabecera, 'cuf').text = cuf_generado
            etree.SubElement(cabecera, 'cufd').text = cufd_record.cufd
            etree.SubElement(cabecera, 'codigoSucursal').text = str(company.siat_codigo_sucursal or 0)
            etree.SubElement(cabecera, 'direccion').text = (company.street or 'Sin direccion')[:500]

            codigo_punto_venta = etree.SubElement(cabecera, 'codigoPuntoVenta')
            if company.siat_codigo_punto_venta:
                codigo_punto_venta.text = str(company.siat_codigo_punto_venta)
            else:
                codigo_punto_venta.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            fecha_emision = ahora_bolivia.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            etree.SubElement(cabecera, 'fechaEmision').text = fecha_emision

            # Datos del cliente
            etree.SubElement(cabecera, 'nombreRazonSocial').text = partner.name[:500]
            etree.SubElement(cabecera, 'codigoTipoDocumentoIdentidad').text = str(
                partner.siat_codigo_tipo_documento or 5)
            etree.SubElement(cabecera, 'numeroDocumento').text = str(partner.vat)[:20]

            complemento_elem = etree.SubElement(cabecera, 'complemento')
            if partner.siat_complemento:
                complemento_elem.text = partner.siat_complemento[:5]
            else:
                complemento_elem.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            codigo_cliente = partner.codigo_cliente or partner.vat or f'CLI-{partner.id}'
            etree.SubElement(cabecera, 'codigoCliente').text = str(codigo_cliente)[:100]

            codigo_metodo_pago = str(self.siat_metodo_pago_id.codigo_clasificador) if self.siat_metodo_pago_id else '1'
            etree.SubElement(cabecera, 'codigoMetodoPago').text = codigo_metodo_pago

            numero_tarjeta = etree.SubElement(cabecera, 'numeroTarjeta')
            numero_tarjeta.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            # ================================================================
            # CALCULAR MONTO TOTAL CON DECIMAL (SIN CONVERSIÓN A FLOAT)
            # ================================================================
            if self.siat_es_moneda_extranjera:
                monto_total_bob_decimal = Decimal('0.0')

                for line in self.invoice_line_ids:
                    # Excluir línea de descuento global
                    if self._es_linea_descuento_global(line):
                        continue
                        
                    if line.product_id:
                        product_tmpl = line.product_id.product_tmpl_id
                        if product_tmpl.siat_homologado:
                            # Usar Decimal para precisión exacta
                            precio_unit_decimal = Decimal(str(line.price_unit))
                            tipo_cambio_decimal = Decimal(str(self.siat_tipo_cambio))
                            cantidad_decimal = Decimal(str(line.quantity))

                            # Calcular precio en BOB
                            precio_bob_decimal = precio_unit_decimal * tipo_cambio_decimal

                            # REDONDEAR PRECIO PRIMERO (CRÍTICO)
                            precio_bob_decimal = precio_bob_decimal.quantize(
                                Decimal('0.01'),
                                rounding=ROUND_HALF_UP
                            )

                            # Calcular subtotal con precio ya redondeado
                            subtotal_decimal = cantidad_decimal * precio_bob_decimal

                            # Redondear subtotal
                            subtotal_bob_decimal = subtotal_decimal.quantize(
                                Decimal('0.01'),
                                rounding=ROUND_HALF_UP
                            )

                            _logger.error(
                                f"DEBUG: subtotal_decimal={subtotal_decimal}, subtotal_bob_decimal={subtotal_bob_decimal}, tipo={type(subtotal_bob_decimal)}")

                            # Sumar al total (mantener como Decimal)
                            monto_total_bob_decimal += subtotal_bob_decimal

                # Convertir a float SOLO para el XML
                # montoTotal = suma de subtotales - descuento global
                monto_total_bob = float(monto_total_bob_decimal) - descuento_global
                tipo_cambio = round(self.siat_tipo_cambio, 2)
                monto_moneda = round(self.siat_monto_total_moneda, 2)

                _logger.info("╔" + "=" * 80 + "╗")
                _logger.info(f"║ MONTOS EN XML (MONEDA EXTRANJERA):")
                _logger.info(f"║   • Suma subtotales: {float(monto_total_bob_decimal):.2f} BOB")
                _logger.info(f"║   • Descuento global: {descuento_global:.2f} BOB")
                _logger.info(f"║   • montoTotal (BOB): {monto_total_bob:.2f}")
                _logger.info(f"║   • codigoMoneda: 1 (BOB)")
                _logger.info(f"║   • tipoCambio: {tipo_cambio:.2f}")
                _logger.info(f"║   • montoTotalMoneda ({self.currency_id.name}): {monto_moneda:.2f}")
                _logger.info("╚" + "=" * 80 + "╝")
            else:
                # FACTURA EN BOB - Calcular suma de subtotales excluyendo descuento global
                suma_subtotales = Decimal('0.0')
                for line in self.invoice_line_ids:
                    if self._es_linea_descuento_global(line):
                        continue
                    if line.product_id and line.product_id.product_tmpl_id.siat_homologado:
                        subtotal = Decimal(str(line.quantity)) * Decimal(str(line.price_unit))
                        subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        suma_subtotales += subtotal
                
                # montoTotal = suma de subtotales - descuento global
                monto_total_bob = float(suma_subtotales) - descuento_global
                tipo_cambio = 1.00
                monto_moneda = monto_total_bob

                _logger.info("╔" + "=" * 80 + "╗")
                _logger.info(f"║ MONTOS EN XML (BOB):")
                _logger.info(f"║   • Suma subtotales: {float(suma_subtotales):.2f} BOB")
                _logger.info(f"║   • Descuento global: {descuento_global:.2f} BOB")
                _logger.info(f"║   • montoTotal: {monto_total_bob:.2f} BOB")
                _logger.info("╚" + "=" * 80 + "╝")

            etree.SubElement(cabecera, 'montoTotal').text = f"{monto_total_bob:.2f}"
            etree.SubElement(cabecera, 'montoTotalSujetoIva').text = f"{monto_total_bob:.2f}"
            etree.SubElement(cabecera, 'codigoMoneda').text = '1'  # Siempre 1 (BOB)
            etree.SubElement(cabecera, 'tipoCambio').text = f"{tipo_cambio:.2f}"
            etree.SubElement(cabecera, 'montoTotalMoneda').text = f"{monto_moneda:.2f}"
            etree.SubElement(cabecera, 'montoGiftCard').text = '0'
            etree.SubElement(cabecera, 'descuentoAdicional').text = f"{descuento_global:.2f}"
            etree.SubElement(cabecera, 'codigoExcepcion').text = '1'

            cafc = etree.SubElement(cabecera, 'cafc')
            cafc.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            etree.SubElement(cabecera, 'leyenda').text = leyenda[:200]
            etree.SubElement(cabecera, 'usuario').text = self.env.user.name[:100]
            etree.SubElement(cabecera, 'codigoDocumentoSector').text = '1'

            # Agregar líneas de factura
            self._agregar_detalle_xml(root)

            xml_string = etree.tostring(
                root,
                pretty_print=True,
                xml_declaration=True,
                encoding='UTF-8',
                standalone=True
            ).decode('utf-8')

            # Guardar datos
            self.write({
                'siat_xml_factura': xml_string,
                'siat_cuf': cuf_generado,
                'siat_numero_factura': numero_factura
            })

            _logger.info("✓ XML generado exitosamente")

            # Firma digital para modalidad Electronica En Linea
            xml_a_enviar = xml_string
            if self._es_modalidad_electronica():
                _logger.info("Modalidad Electronica - enviando al microservicio de firma...")
                config = self.company_id.siat_config_id
                xml_firmado = self._firmar_xml_electronico(xml_string, config)
                self.write({'siat_xml_factura': xml_firmado})
                xml_a_enviar = xml_firmado
                _logger.info("✓ XML firmado y guardado")

            # Enviar a SIAT
            self._enviar_factura_a_siat_invoice(xml_a_enviar, cufd_record)

            return xml_string

        except Exception as e:
            _logger.error(f"Error generando XML: {str(e)}", exc_info=True)
            raise

    def _agregar_detalle_xml(self, root):
        """Agrega las líneas de detalle al XML"""
        for line in self.invoice_line_ids:
            if not line.product_id:
                continue

            # Excluir línea de descuento global del detalle
            if self._es_linea_descuento_global(line):
                _logger.info(f"Línea de descuento global excluida del detalle XML")
                continue

            product = line.product_id
            product_tmpl = product.product_tmpl_id

            if not product_tmpl.siat_homologado:
                _logger.warning(f"Producto {product.name} no homologado, saltando...")
                continue

            detalle = etree.SubElement(root, 'detalle')

            etree.SubElement(detalle, 'actividadEconomica').text = str(product_tmpl.siat_codigo_actividad or '')[:10]
            etree.SubElement(detalle, 'codigoProductoSin').text = str(product_tmpl.siat_codigo_producto or '0')
            etree.SubElement(detalle, 'codigoProducto').text = (product.default_code or f'PROD-{product.id}')[:50]
            etree.SubElement(detalle, 'descripcion').text = line.name[:500] if line.name else product.name[:500]
            etree.SubElement(detalle, 'cantidad').text = f"{line.quantity:.2f}"
            etree.SubElement(detalle, 'unidadMedida').text = str(product_tmpl.siat_codigo_unidad_medida or 58)

            if self.siat_es_moneda_extranjera:
                # ================================================================
                # USAR DECIMAL - MANTENER COMO DECIMAL HASTA EL ÚLTIMO MOMENTO
                # ================================================================
                # Convertir a Decimal para precisión exacta
                precio_unit_decimal = Decimal(str(line.price_unit))
                tipo_cambio_decimal = Decimal(str(self.siat_tipo_cambio))
                cantidad_decimal = Decimal(str(line.quantity))

                # Calcular precio en BOB con precisión
                precio_unitario_bob_decimal = precio_unit_decimal * tipo_cambio_decimal

                precio_unitario_bob_decimal = precio_unitario_bob_decimal.quantize(
                    Decimal('0.01'),
                    rounding=ROUND_HALF_UP
                )

                # Calcular subtotal con precio ya redondeado
                subtotal_decimal = cantidad_decimal * precio_unitario_bob_decimal

                # Redondear subtotal
                subtotal_bob_decimal = subtotal_decimal.quantize(
                    Decimal('0.01'),
                    rounding=ROUND_HALF_UP
                )

                # Escribir al XML - convertir directamente de Decimal a string
                # NO usar float() aquí para evitar errores de representación
                etree.SubElement(detalle, 'precioUnitario').text = str(precio_unitario_bob_decimal)

                # montoDescuento por línea = nil (usamos descuento global)
                monto_descuento = etree.SubElement(detalle, 'montoDescuento')
                monto_descuento.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

                etree.SubElement(detalle, 'subTotal').text = str(subtotal_bob_decimal)

                _logger.info(
                    f"Detalle: {line.price_unit:.2f} {self.currency_id.name} × {self.siat_tipo_cambio:.2f} "
                    f"= {float(precio_unitario_bob_decimal):.6f} BOB × {line.quantity:.2f} "
                    f"= {float(subtotal_decimal):.6f} → {float(subtotal_bob_decimal):.2f} BOB"
                )
            else:
                # Mantener en BOB (ya está en BOB)
                etree.SubElement(detalle, 'precioUnitario').text = f"{line.price_unit:.2f}"

                # montoDescuento por línea = nil (usamos descuento global)
                monto_descuento = etree.SubElement(detalle, 'montoDescuento')
                monto_descuento.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

                subtotal = round(line.quantity * line.price_unit, 2)
                etree.SubElement(detalle, 'subTotal').text = f"{subtotal:.2f}"

            serie = etree.SubElement(detalle, 'numeroSerie')
            serie.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            imei = etree.SubElement(detalle, 'numeroImei')
            imei.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

    def _enviar_factura_a_siat_invoice(self, xml_string, cufd_record):
        """Envía la factura a SIAT"""
        self.ensure_one()

        try:
            company = self.company_id
            config = company.siat_config_id

            if not config:
                raise ValidationError("No se encontró configuración SIAT")

            # Obtener CUIS
            cuis_model = self.env['alpha.siat.cuis']
            cuis = cuis_model.get_or_fetch_cuis(company, codigo_modalidad=int(config.modalidad))

            # Enviar factura
            client = self.env['alpha.siat.client'].sudo()
            resultado = client.enviar_factura_siat(
                company=company,
                config=config,
                cuis=cuis,
                cufd=cufd_record.cufd,
                xml_string=xml_string
            )

            # Verificar resultado
            if resultado.get('error'):
                estado = resultado.get('estado', 'ERROR')
                mensajes = resultado.get('mensajes', 'Error desconocido')

                error_msg = (
                    f"FACTURA RECHAZADA POR SIAT\n\n"
                    f"Estado: {estado}\n"
                    f"Mensaje: {mensajes}\n\n"
                    f"La factura no fue aceptada por SIAT."
                )

                self.write({
                    'siat_estado_envio': estado,
                    'siat_mensajes_envio': mensajes,
                    'siat_fecha_envio': fields.Datetime.now()
                })

                raise ValidationError(error_msg)

            # Guardar resultado exitoso
            self.write({
                'siat_estado_envio': resultado.get('estado', ''),
                'siat_codigo_recepcion': resultado.get('codigoRecepcion', ''),
                'siat_mensajes_envio': resultado.get('mensajes', ''),
                'siat_fecha_envio': fields.Datetime.now()
            })

            _logger.info("=" * 100)
            _logger.info("✓ FACTURA ACEPTADA POR SIAT")
            _logger.info(f"  Moneda: {self.currency_id.name}")
            _logger.info(f"  Estado: {resultado.get('estado', '')}")
            _logger.info(f"  Código Recepción: {resultado.get('codigoRecepcion', '')}")
            _logger.info("=" * 100)

            if self.siat_emails_destinatarios:
                _logger.info("Intentando enviar PDF por correo...")
                self._enviar_pdf_por_correo()

            return {
                'success': True,
                'estado': resultado.get('estado', ''),
                'codigo_recepcion': resultado.get('codigoRecepcion', '')
            }

        except ValidationError:
            raise
        except Exception as e:
            error_msg = f"Error enviando factura a SIAT: {str(e)}"
            _logger.error(error_msg, exc_info=True)
            raise ValidationError(error_msg)

    def action_post(self):
        res = super(AccountMove, self).action_post()

        for move in self:
            if move.move_type in ['out_invoice', 'out_refund']:
                try:
                    _logger.info("=" * 100)
                    _logger.info(f"CONFIRMANDO FACTURA - Enviando automáticamente a SIAT: {move.name}")
                    _logger.info("=" * 100)

                    # Validar requisitos SIAT
                    move._validar_requisitos_siat_invoice()

                    # Generar y enviar factura
                    xml_generado = move._generar_xml_factura_siat_invoice()

                    if xml_generado:
                        _logger.info("✓ FACTURA ENVIADA EXITOSAMENTE A SIAT")
                        _logger.info(f"  CUF: {move.siat_cuf}")
                        _logger.info(f"  Código Recepción: {move.siat_codigo_recepcion}")

                except UserError as e:
                    # Si hay error de validación, revertir la confirmación
                    _logger.error(f"Error al enviar a SIAT: {str(e)}")
                    move.button_draft()  # Revertir a borrador
                    raise UserError(
                        f"ERROR AL ENVIAR A SIAT\n\n"
                        f"La factura no pudo ser confirmada porque:\n\n"
                        f"{str(e)}\n\n"
                        f"La factura ha sido devuelta a estado borrador."
                    )
                except Exception as e:
                    _logger.error(f"Error inesperado al enviar a SIAT: {str(e)}", exc_info=True)
                    move.button_draft()  # Revertir a borrador
                    raise UserError(
                        f"ERROR INESPERADO AL ENVIAR A SIAT\n\n"
                        f"{str(e)}\n\n"
                        f"La factura ha sido devuelta a estado borrador."
                    )

        return res

    def action_anular_factura_siat(self):
        self.ensure_one()

        _logger.info("=" * 100)
        _logger.info(f"INICIANDO ANULACIÓN DE FACTURA: {self.name}")
        _logger.info("=" * 100)

        # Validaciones básicas
        if not self.siat_facturado:
            raise UserError(
                "FACTURA NO ENVIADA A SIAT\n\n"
                "Esta factura no ha sido enviada a SIAT previamente.\n"
                "Debe enviarla primero con el botón 'Enviar a SIAT'."
            )

        if self.siat_anulado:
            raise UserError(
                "FACTURA YA ANULADA\n\n"
                f"Esta factura ya fue anulada en SIAT.\n"
                f"Fecha de anulación: {self.siat_fecha_anulacion}"
            )

        if not self.siat_cuf:
            raise UserError(
                "CUF NO ENCONTRADO\n\n"
                "No se encontró el CUF de esta factura.\n"
                "Sin el CUF no es posible anular en SIAT."
            )

        try:
            company = self.company_id
            config = company.siat_config_id

            if not config:
                raise UserError("No se encontró configuración SIAT para esta compañía.")

            _logger.info(f"Compañía: {company.name}")
            _logger.info(f"NIT: {company.vat}")
            _logger.info(f"CUF a anular: {self.siat_cuf}")

            # Obtener CUIS
            cuis_model = self.env['alpha.siat.cuis']
            cuis = cuis_model.get_or_fetch_cuis(company, codigo_modalidad=int(config.modalidad))

            # Obtener CUFD
            cufd_model = self.env['alpha.siat.cufd']
            cufd = cufd_model.get_or_fetch_cufd(company)

            _logger.info(f"CUIS: {cuis[:20]}...")
            _logger.info(f"CUFD: {cufd[:20]}...")

            # Preparar datos de anulación
            datos_anulacion = {
                'codigoAmbiente': int(config.codigo_ambiente),
                'codigoPuntoVenta': company.siat_codigo_punto_venta or 0,
                'codigoSistema': config.codigo_sistema or '',
                'codigoSucursal': company.siat_codigo_sucursal or 0,
                'nit': (company.vat or '').strip(),
                'codigoDocumentoSector': 1,
                'codigoEmision': 1,
                'codigoModalidad': int(config.modalidad),
                'cufd': cufd,
                'cuis': cuis,
                'tipoFacturaDocumento': 1,
                'codigoMotivo': 1,
                'cuf': self.siat_cuf,
            }

            _logger.info("Enviando solicitud de anulación a SIAT...")

            # Enviar anulación a SIAT
            client = self.env['alpha.siat.client'].sudo()
            resultado = client.anular_factura_siat(
                company=company,
                config=config,
                datos_anulacion=datos_anulacion
            )

            if resultado.get('error'):
                error_msg = resultado.get('mensajes', 'Error desconocido')
                _logger.error(f"Error en SIAT: {error_msg}")
                raise UserError(
                    f"ERROR AL ANULAR EN SIAT\n\n"
                    f"Estado: {resultado.get('estado', 'ERROR')}\n"
                    f"Mensaje: {error_msg}\n\n"
                    f"La factura no fue anulada."
                )

            # Guardar estado de anulación
            self.write({
                'siat_anulado': True,
                'siat_fecha_anulacion': fields.Datetime.now(),
                'siat_motivo_anulacion': 1,
            })

            _logger.info("✓ Factura anulada exitosamente en SIAT")

            # Cancelar la factura en Odoo
            if self.state == 'posted':
                _logger.info("Cancelando factura en Odoo...")
                self.button_draft()
                self.button_cancel()
                _logger.info("✓ Factura cancelada en Odoo")

            _logger.info("=" * 100)
            _logger.info("✓ PROCESO DE ANULACIÓN COMPLETADO EXITOSAMENTE")
            _logger.info("=" * 100)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': '✓ Factura Anulada',
                    'message': f'La factura {self.name} fue anulada en SIAT y cancelada en Odoo.',
                    'type': 'success',
                    'sticky': False,
                }
            }

        except UserError:
            raise
        except Exception as e:
            _logger.error(f"Error crítico al anular factura: {str(e)}", exc_info=True)
            raise UserError(f"Error al anular: {str(e)}")

    def _validar_emails(self, emails_str):
        """Valida que los emails sean correctos"""
        import re
        if not emails_str:
            return []

        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        emails = [email.strip() for email in emails_str.split(',')]
        emails_validos = []

        for email in emails:
            if email and re.match(email_pattern, email):
                emails_validos.append(email)
            elif email:
                _logger.warning(f"Email inválido ignorado: {email}")

        return emails_validos

    def _enviar_pdf_por_correo(self):
        """Envía el PDF de la factura por correo electrónico"""
        self.ensure_one()

        if not self.siat_emails_destinatarios:
            _logger.info("No hay emails configurados para envío")
            return False

        emails_validos = self._validar_emails(self.siat_emails_destinatarios)
        if not emails_validos:
            _logger.warning("No hay emails válidos para envío")
            return False

        try:
            IrMailServer = self.env['ir.mail_server']
            if not IrMailServer.sudo().search([], limit=1):
                _logger.warning(
                    "No hay servidor de correo configurado. "
                    "Configure uno en: Ajustes > Técnico > Correo electrónico > Servidores de correo saliente"
                )
                return False

            company = self.company_id
            attachments = []

            _logger.info(f"Generando PDF personalizado para factura {self.name}...")

            try:
                pdf_content = self._generar_pdf_factura_siat()

                pdf_attachment = self.env['ir.attachment'].create({
                    'name': f'Factura_SIAT_{self.siat_numero_factura}.pdf',
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'res_model': 'account.move',
                    'res_id': self.id,
                    'mimetype': 'application/pdf'
                })
                attachments.append(pdf_attachment.id)
                _logger.info("✓ PDF personalizado generado correctamente")

            except Exception as e:
                _logger.error(f"Error generando PDF personalizado: {str(e)}", exc_info=True)
                _logger.warning("Intentando con PDF estándar como fallback...")
                pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                    'account.account_invoices',
                    [self.id]
                )
                pdf_attachment = self.env['ir.attachment'].create({
                    'name': f'Factura_{self.name}.pdf',
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content),
                    'res_model': 'account.move',
                    'res_id': self.id,
                    'mimetype': 'application/pdf'
                })
                attachments.append(pdf_attachment.id)

            if self.siat_xml_factura:
                _logger.info("Adjuntando XML de factura SIAT...")

                xml_attachment = self.env['ir.attachment'].create({
                    'name': f'Factura_SIAT_{self.siat_numero_factura}.xml',
                    'type': 'binary',
                    'datas': base64.b64encode(self.siat_xml_factura.encode('utf-8')),
                    'res_model': 'account.move',
                    'res_id': self.id,
                    'mimetype': 'application/xml'
                })
                attachments.append(xml_attachment.id)
                _logger.info("✓ XML adjuntado correctamente")
            else:
                _logger.warning("No hay XML de factura SIAT para adjuntar")

            body_html = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">Factura Electrónica</h1>
                    <p style="color: #f0f0f0; margin-top: 10px;">Documento Fiscal Digital</p>
                </div>

                <div style="background: #ffffff; padding: 30px; border: 1px solid #e0e0e0; border-top: none;">
                    <p style="font-size: 16px; color: #333;">Estimado/a <strong>{self.partner_id.name}</strong>,</p>

                    <p style="color: #666; line-height: 1.6;">
                        Adjuntamos su factura electrónica emitida y validada por el Servicio de Impuestos Nacionales (SIAT).
                    </p>

                    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="color: #667eea; margin-top: 0; border-bottom: 2px solid #667eea; padding-bottom: 10px;">
                            Detalles de la Factura
                        </h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 8px 0; color: #666; font-weight: bold; width: 40%;">Número de Factura:</td>
                                <td style="padding: 8px 0; color: #333;">{self.name}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #666; font-weight: bold;">Factura SIAT N°:</td>
                                <td style="padding: 8px 0; color: #333;">{self.siat_numero_factura}</td>
                            </tr>
                            <tr>
                                <td style="padding: 8px 0; color: #666; font-weight: bold;">Fecha de Emisión:</td>
                                <td style="padding: 8px 0; color: #333;">{self.invoice_date.strftime('%d/%m/%Y') if self.invoice_date else ''}</td>
                            </tr>
                            <tr style="background: #e8eaf6;">
                                <td style="padding: 12px 8px; color: #667eea; font-weight: bold; font-size: 18px;">Monto Total:</td>
                                <td style="padding: 12px 8px; color: #667eea; font-weight: bold; font-size: 18px;">
                                    {self.currency_id.symbol} {self.amount_total:,.2f}
                                </td>
                            </tr>
                        </table>
                    </div>

                    <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 4px;">
                        <p style="margin: 0; color: #856404; font-size: 14px;">
                            <strong>Archivos adjuntos:</strong><br/>
                            • PDF de la factura (Representación gráfica)<br/>
                            • XML de la factura (Documento fiscal digital)
                        </p>
                    </div>

                    <p style="color: #666; line-height: 1.6; margin-top: 20px;">
                        Puede verificar la autenticidad de esta factura en el sitio web del SIN ingresando el CUF.
                    </p>

                    <p style="color: #666; line-height: 1.6;">
                        Gracias por su preferencia.
                    </p>
                </div>

                <div style="background: #f8f9fa; padding: 20px; text-align: center; border-radius: 0 0 10px 10px; border: 1px solid #e0e0e0; border-top: none;">
                    <p style="color: #666; margin: 0; font-size: 14px; line-height: 1.6;">
                        <strong style="color: #333;">{company.name}</strong><br/>
                        Tel: {company.phone or ''} {' | Email: ' + company.email if company.email else ''}
                    </p>
                    <p style="color: #999; font-size: 11px; margin-top: 15px;">
                        Este es un correo automático, por favor no responder.
                    </p>
                </div>
            </div>
            """

            mail_values = {
                'subject': f'✓ Factura {self.name} - {company.name}',
                'body_html': body_html,
                'email_from': company.email or self.env.user.email,
                'email_to': ','.join(emails_validos),
                'attachment_ids': [(6, 0, attachments)],
                'auto_delete': True,
            }

            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()

            _logger.info("=" * 100)
            _logger.info("✓ CORREO ENVIADO EXITOSAMENTE")
            _logger.info(f"  Destinatarios: {', '.join(emails_validos)}")
            _logger.info(f"  PDF: Factura_SIAT_{self.siat_numero_factura}.pdf")
            _logger.info(f"  XML: Factura_SIAT_{self.siat_numero_factura}.xml")
            _logger.info("=" * 100)

            self.message_post(
                body=f"""
                <p><strong>Factura enviada por correo electrónico</strong></p>
                <ul>
                    <li><strong>Destinatarios:</strong> {', '.join(emails_validos)}</li>
                    <li><strong>Archivos adjuntos:</strong></li>
                    <ul>
                        <li>PDF: Factura_SIAT_{self.siat_numero_factura}.pdf</li>
                        <li>XML: Factura_SIAT_{self.siat_numero_factura}.xml</li>
                    </ul>
                </ul>
                """,
                subject="✓ Factura enviada por correo"
            )

            return True

        except Exception as e:
            _logger.error(f"Error enviando correo: {str(e)}", exc_info=True)

            try:
                self.message_post(
                    body=f"<p><strong>Error al enviar factura por correo:</strong><br/>{str(e)}</p>",
                    subject="Error en envío de correo"
                )
            except:
                pass

            return False