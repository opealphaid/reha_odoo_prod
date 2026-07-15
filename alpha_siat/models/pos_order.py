import logging
from odoo import models, api, fields
from odoo.exceptions import UserError, ValidationError
from lxml import etree
from datetime import datetime, timedelta, timezone
import random

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    siat_xml_factura = fields.Text(
        string="XML Factura SIAT",
        readonly=True,
        help="XML generado para enviar a SIAT"
    )

    siat_cuf = fields.Char(
        string="CUF",
        readonly=True,
        help="Codigo Unico de Factura"
    )

    siat_numero_factura = fields.Integer(
        string="Numero Factura SIAT",
        readonly=True,
        help="Numero de factura para SIAT"
    )

    siat_estado_envio = fields.Char(
        string="Estado Envío SIAT",
        readonly=True,
        help="Estado del envío a SIAT (908=Validado, 904=Observado)"
    )

    siat_codigo_recepcion = fields.Char(
        string="Código Recepción SIAT",
        readonly=True,
        help="Código de recepción devuelto por SIAT"
    )

    siat_mensajes_envio = fields.Text(
        string="Mensajes SIAT",
        readonly=True,
        help="Mensajes devueltos por SIAT"
    )

    siat_fecha_envio = fields.Datetime(
        string="Fecha Envío SIAT",
        readonly=True
    )

    siat_facturado = fields.Boolean(
        string='Facturado en SIAT',
        readonly=True,
        copy=False,
        compute='_compute_siat_facturado',
        store=True,
        help='Indica si la orden fue enviada y aceptada por SIAT'
    )

    siat_anulado = fields.Boolean(
        string='Anulado en SIAT',
        readonly=True,
        copy=False,
        default=False,
        help='Indica si la orden fue anulada en SIAT'
    )

    siat_fecha_anulacion = fields.Datetime(
        string='Fecha Anulación SIAT',
        readonly=True,
        copy=False,
        help='Fecha y hora en que se anuló la orden en SIAT'
    )

    siat_motivo_anulacion = fields.Integer(
        string='Código Motivo Anulación',
        readonly=True,
        copy=False,
        help='Código del motivo de anulación (1=Genérico)'
    )

    @api.depends('siat_estado_envio', 'siat_codigo_recepcion')
    def _compute_siat_facturado(self):
        """Calcula si la orden fue aceptada por SIAT"""
        for order in self:
            order.siat_facturado = bool(
                order.siat_estado_envio == '908' and
                order.siat_codigo_recepcion
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            to_invoice = vals.get('to_invoice', False)

            if to_invoice:
                _logger.info("[CREATE] Orden requiere factura - validando requisitos SIAT")
                validation_result = self._validar_requisitos_siat(vals)
                if not validation_result['success']:
                    _logger.error(f"[CREATE] Validacion fallida: {validation_result['message']}")
                    raise UserError(validation_result['message'])

                self._log_pos_order_details(vals)
            else:
                _logger.info("[CREATE] Orden NO requiere factura")

        orders = super().create(vals_list)

        for order in orders:
            if order.to_invoice:
                try:
                    _logger.info(f"[CREATE] Generando factura para orden {order.name}")
                    xml_generado = order._generar_xml_factura_siat()

                    if not xml_generado:
                        error_msg = (
                            "ERROR GENERANDO FACTURA\n\n"
                            "No se pudo generar la factura electrónica.\n"
                            "La venta no puede completarse."
                        )
                        _logger.error(f"[CREATE] {error_msg}")
                        raise UserError(error_msg)

                    _logger.info(f"[CREATE] ✓ Factura generada exitosamente para orden {order.name}")

                except UserError:
                    raise
                except Exception as e:
                    error_msg = (
                        f"ERROR GENERANDO FACTURA\n\n"
                        f"Ocurrió un error al generar la factura:\n"
                        f"{str(e)}\n\n"
                        f"La venta no puede completarse."
                    )
                    _logger.error(f"[CREATE] Error: {error_msg}", exc_info=True)
                    raise UserError(error_msg)

        return orders

    def write(self, vals):
        """Intercepta la actualizacion de ordenes POS (mesas ocupadas)"""

        for order in self:
            state = vals.get('state')
            to_invoice = vals.get('to_invoice', order.to_invoice)

            if state in ['paid', 'done'] and to_invoice and not order.siat_xml_factura:
                _logger.info("=" * 100)
                _logger.info(
                    f"[WRITE-VALIDACION] Orden {order.name} requiere factura - Validando ANTES de confirmar pago")
                _logger.info("=" * 100)

                try:
                    # Validar requisitos SIAT ANTES de confirmar
                    vals_validacion = {
                        'partner_id': order.partner_id.id,
                        'company_id': order.company_id.id,
                        'session_id': order.session_id.id,
                        'to_invoice': to_invoice,
                        'lines': [(0, 0, {
                            'product_id': line.product_id.id,
                            'qty': line.qty,
                            'price_unit': line.price_unit,
                        }) for line in order.lines]
                    }

                    validation_result = order._validar_requisitos_siat(vals_validacion)
                    if not validation_result['success']:
                        _logger.error(f"[WRITE-VALIDACION] Validacion fallida: {validation_result['message']}")
                        raise UserError(validation_result['message'])

                    _logger.info("[WRITE-VALIDACION] ✓ Validaciones pasadas correctamente")

                except UserError:
                    # Re-lanzar UserError directamente
                    raise
                except Exception as e:
                    error_msg = (
                        f"ERROR DE VALIDACION SIAT\n\n"
                        f"No se puede completar la venta con factura debido a:\n"
                        f"{str(e)}\n\n"
                        f"La venta ha sido bloqueada."
                    )
                    _logger.error(f"[WRITE-VALIDACION] Error critico: {error_msg}", exc_info=True)
                    raise UserError(error_msg)

        result = super().write(vals)

        for order in self:
            state = vals.get('state')
            to_invoice = vals.get('to_invoice', order.to_invoice)

            should_generate = (
                    state in ['paid', 'done'] and
                    to_invoice and
                    not order.siat_xml_factura
            )

            if should_generate:
                try:
                    _logger.info("=" * 100)
                    _logger.info(f"[WRITE-FACTURACION] Generando factura para orden {order.name}")
                    _logger.info("=" * 100)

                    xml_generado = order._generar_xml_factura_siat()

                    if xml_generado:
                        _logger.info(f"[WRITE-FACTURACION] ✓ Factura generada exitosamente para orden {order.name}")
                    else:
                        error_msg = (
                            "ERROR GENERANDO FACTURA\n\n"
                            "No se pudo generar la factura electrónica.\n"
                            "La venta no puede completarse."
                        )
                        _logger.error(f"[WRITE-FACTURACION] {error_msg}")
                        raise UserError(error_msg)

                except UserError:
                    raise
                except Exception as e:
                    error_msg = (
                        f"ERROR GENERANDO FACTURA\n\n"
                        f"Ocurrió un error al generar la factura:\n"
                        f"{str(e)}\n\n"
                        f"La venta no puede completarse."
                    )
                    _logger.error(f"[WRITE-FACTURACION] Error: {error_msg}", exc_info=True)
                    raise UserError(error_msg)

            elif state in ['paid', 'done'] and not to_invoice:
                _logger.info(f"[WRITE] Orden {order.name} - Estado: {state} - NO requiere factura")

            if 'account_move' in vals:
                for order in self:
                    if order.siat_cuf and order.account_move:
                        _logger.info("=" * 100)
                        _logger.info(f"[SYNC] Sincronizando datos SIAT a factura {order.account_move.name}")
                        _logger.info("=" * 100)

                        try:
                            order.account_move.write({
                                'siat_xml_factura': order.siat_xml_factura,
                                'siat_cuf': order.siat_cuf,
                                'siat_numero_factura': order.siat_numero_factura,
                                'siat_estado_envio': order.siat_estado_envio,
                                'siat_codigo_recepcion': order.siat_codigo_recepcion,
                                'siat_mensajes_envio': order.siat_mensajes_envio,
                                'siat_fecha_envio': order.siat_fecha_envio,
                            })

                            _logger.info(f"[SYNC] ✓ Datos sincronizados - CUF: {order.siat_cuf}")

                        except Exception as e:
                            _logger.error(f"[SYNC] Error: {str(e)}", exc_info=True)
        return result

    def _validar_requisitos_siat(self, vals):
        """Valida que existan todos los requisitos para generar factura SIAT"""

        # Obtener company
        company_id = vals.get('company_id')
        if not company_id:
            session_id = vals.get('session_id')
            if session_id:
                session = self.env['pos.session'].browse(session_id)
                company_id = session.company_id.id

        if not company_id:
            return {
                'success': False,
                'message': 'No se pudo determinar la compania de la orden',
                'tipo': 'danger'
            }

        company = self.env['res.company'].browse(company_id)

        # Validar cliente
        partner_id = vals.get('partner_id')
        if not partner_id:
            return {
                'success': False,
                'message': (
                    'CLIENTE NO SELECCIONADO\n\n'
                    'Debe seleccionar un cliente para poder facturar.\n'
                    'Por favor, seleccione un cliente antes de validar la orden.'
                ),
                'tipo': 'danger'
            }

        partner = self.env['res.partner'].browse(partner_id)

        # Validar que el cliente este homologado
        if not partner.siat_homologado_cliente:
            errores_cliente = []
            if not partner.vat:
                errores_cliente.append('- NIT/CI')
            if not partner.siat_tipo_documento_identidad_id:
                errores_cliente.append('- Tipo de Documento de Identidad')

            mensaje_error = (
                f'CLIENTE NO HOMOLOGADO: {partner.name}\n\n'
                'El cliente no esta homologado para facturacion SIAT.\n\n'
                'Campos faltantes:\n'
            )
            mensaje_error += '\n'.join(errores_cliente)
            mensaje_error += (
                '\n\nPor favor, complete los datos del cliente en:\n'
                'Contactos > Seleccione el cliente > Complete los campos SIAT'
            )

            return {
                'success': False,
                'message': mensaje_error,
                'tipo': 'danger'
            }

        # Validar NIT/CI del cliente
        if not partner.vat:
            return {
                'success': False,
                'message': (
                    f'CLIENTE SIN NIT/CI: {partner.name}\n\n'
                    'El cliente no tiene NIT/CI configurado.\n'
                    'Por favor, configure el NIT/CI del cliente antes de facturar.'
                ),
                'tipo': 'danger'
            }

        # Validar CUFD
        cufd = self._obtener_cufd_valido_por_company(company)
        if not cufd:
            return {
                'success': False,
                'message': (
                    'NO HAY CUFD VALIDO DISPONIBLE\n\n'
                    'No se puede generar la factura porque no existe un CUFD valido.\n'
                    'Por favor, sincronice el CUFD desde:\n'
                    'Facturacion > Configuracion > SIAT > Sincronizar CUFD'
                ),
                'tipo': 'warning'
            }

        # Validar productos homologados
        lines = vals.get('lines', [])
        non_homologated_products = []

        for line in lines:
            if isinstance(line, (list, tuple)) and len(line) >= 3:
                line_data = line[2]
            else:
                line_data = line

            product_id = line_data.get('product_id')
            if product_id:
                product = self.env['product.product'].browse(product_id)
                if not product.product_tmpl_id.siat_homologado:
                    non_homologated_products.append(product.name)

        if non_homologated_products:
            productos_str = '\n- '.join(non_homologated_products)
            return {
                'success': False,
                'message': (
                    'PRODUCTOS NO HOMOLOGADOS\n\n'
                    'Los siguientes productos NO estan homologados para facturacion SIAT:\n\n'
                    f'- {productos_str}\n\n'
                    'Por favor, homologue los productos antes de continuar.\n'
                    'Vaya a: Inventario > Productos > Seleccione el producto > Complete los datos SIAT'
                ),
                'tipo': 'warning'
            }

        return {'success': True, 'message': 'Validacion exitosa', 'tipo': 'success'}

    def _es_modalidad_electronica(self):
        """Retorna True si la configuracion SIAT es modalidad Electronica En Linea"""
        config = self.company_id.siat_config_id
        if not config:
            config = self.env['alpha.siat.config'].search([], limit=1)
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
        _logger.info(f"[POS FIRMA] Enviando XML al microservicio: {url_firma}")
        _logger.info(f"[POS FIRMA] Tamano XML: {len(xml_string)} chars")
        _logger.info("[POS FIRMA] XML a firmar:")
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
            _logger.info(f"[POS FIRMA] HTTP Status: {response.status_code}")
            _logger.info(f"[POS FIRMA] Respuesta ({len(response.text)} chars):")
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

            _logger.info("\u2713 [POS FIRMA] XML firmado correctamente")
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

    def _obtener_cufd_valido_por_company(self, company):
        """Obtiene un CUFD valido para la compania especificada"""

        _logger.info(f"Buscando CUFD valido para compania: {company.name}")

        cufd_model = self.env['alpha.siat.cufd']

        # Buscar CUFD válido en estado 'valid'
        cufd_valido = cufd_model.search([
            ('company_id', '=', company.id),
            ('state', '=', 'valid')
        ], limit=1, order='fecha_vigencia desc')

        if cufd_valido:
            # Verificar que realmente esté vigente
            now_utc = datetime.now(timezone.utc)
            bolivia_tz = timezone(timedelta(hours=-4))
            now_bolivia = now_utc.astimezone(bolivia_tz)

            fecha_vigencia = cufd_valido.fecha_vigencia
            if isinstance(fecha_vigencia, str):
                fecha_vigencia = datetime.fromisoformat(fecha_vigencia.replace('Z', '+00:00'))

            if not fecha_vigencia.tzinfo:
                fecha_vigencia = fecha_vigencia.replace(tzinfo=timezone.utc)

            fecha_vigencia_bolivia = fecha_vigencia.astimezone(bolivia_tz)

            _logger.info(f"CUFD encontrado: {cufd_valido.cufd[:20]}...")
            _logger.info(f"  Fecha actual Bolivia: {now_bolivia}")
            _logger.info(f"  Fecha vigencia: {fecha_vigencia_bolivia}")

            if now_bolivia < fecha_vigencia_bolivia:
                tiempo_restante = fecha_vigencia_bolivia - now_bolivia
                horas_restantes = tiempo_restante.total_seconds() / 3600

                _logger.info(f"  ✓ CUFD VALIDO - Tiempo restante: {horas_restantes:.2f} horas")

                # ADVERTENCIA si queda menos de 1 hora
                if horas_restantes < 1:
                    _logger.warning(
                        f"⚠ CUFD proximo a expirar en {horas_restantes:.2f} horas - Se recomienda sincronizar nuevo CUFD")

                return cufd_valido
            else:
                _logger.warning(f"⚠ CUFD expirado: {cufd_valido.cufd[:20]}...")
                # Marcar como expirado
                cufd_valido.write({'state': 'expired'})

        _logger.error("✗ NO HAY CUFD VALIDO DISPONIBLE")

        error_msg = (
            "NO HAY CUFD VALIDO DISPONIBLE\n\n"
            "No se puede generar la factura porque no existe un CUFD vigente.\n\n"
            "Posibles causas:\n"
            "• El CUFD expiró (vigencia de 24 horas)\n"
            "• No se ha sincronizado un CUFD desde SIAT\n"
            "• El último CUFD fue marcado como inválido\n\n"
            "IMPORTANTE: Los CUFD tienen vigencia de 24 horas.\n"
            "Se recomienda sincronizar diariamente al inicio de operaciones.\n\n"
            "La venta no puede completarse hasta obtener un CUFD válido."
        )

        raise UserError(error_msg)

    def _obtener_numero_factura(self):
        """Obtiene el siguiente numero de factura para la compania"""
        self.ensure_one()

        company = self.company_id

        # Buscar la ultima orden POS con numero de factura SIAT
        ultima_orden = self.search([
            ('company_id', '=', company.id),
            ('siat_numero_factura', '>', 0)
        ], order='siat_numero_factura desc', limit=1)

        if ultima_orden:
            siguiente_numero = ultima_orden.siat_numero_factura + 1
            _logger.info(f"Siguiente numero de factura: {siguiente_numero} (basado en ultima orden)")
        else:
            siguiente_numero = 1
            _logger.info(f"Primer numero de factura: {siguiente_numero}")

        return siguiente_numero

    def _generar_cuf_dinamico(self, numero_factura):
        """Genera el CUF dinamicamente usando el generador de CUF"""
        self.ensure_one()

        try:
            cuf_generator = self.env['alpha.siat.cuf.generator']
            resultado = cuf_generator.generar_cuf(
                company_id=self.company_id.id,
                numero_factura=numero_factura
            )

            if resultado and resultado.get('cuf'):
                _logger.info(f"CUF generado exitosamente: {resultado['cuf']}")
                return resultado
            else:
                raise ValidationError("No se pudo generar el CUF")

        except Exception as e:
            _logger.error(f"Error generando CUF: {str(e)}", exc_info=True)
            raise ValidationError(f"Error al generar CUF: {str(e)}")

    def _log_pos_order_details(self, vals):
        """Muestra los detalles de la orden de forma legible"""
        _logger.info("=" * 100)
        _logger.info("NUEVA ORDEN POS - DETALLES COMPLETOS")
        _logger.info("=" * 100)

        pos_reference = vals.get('pos_reference', 'Sin referencia')
        date_order = vals.get('date_order', 'Sin fecha')
        amount_total = vals.get('amount_total', 0)
        amount_tax = vals.get('amount_tax', 0)
        to_invoice = vals.get('to_invoice', False)

        _logger.info(f"\nORDEN: {pos_reference}")
        _logger.info(f"Fecha: {date_order}")
        _logger.info(f"Total: {amount_total:.2f} Bs.")
        _logger.info(f"Impuestos: {amount_tax:.2f} Bs.")
        _logger.info(f"Requiere Factura: {'SI' if to_invoice else 'NO'}")

        partner_id = vals.get('partner_id')
        if partner_id:
            partner = self.env['res.partner'].browse(partner_id)
            _logger.info(f"\nCLIENTE:")
            _logger.info(f"   Nombre: {partner.name}")
            _logger.info(f"   NIT/CI: {partner.vat or 'Sin NIT'}")
            _logger.info(f"   Codigo Cliente: {partner.codigo_cliente or 'Sin codigo'}")
            _logger.info(f"   Homologado SIAT: {'SI' if partner.siat_homologado_cliente else 'NO'}")

        _logger.info("\n" + "=" * 100)

    def _generar_xml_factura_siat(self):
        """Genera el XML de la factura segun el formato SIAT"""
        self.ensure_one()

        _logger.info("=" * 100)
        _logger.info(f"GENERANDO XML FACTURA SIAT PARA ORDEN: {self.name}")
        _logger.info("=" * 100)

        try:
            company = self.company_id
            partner = self.partner_id

            if not company.vat:
                raise ValidationError("La empresa no tiene NIT configurado")
            if not partner:
                raise ValidationError("La orden no tiene cliente asignado")
            if not partner.vat:
                raise ValidationError(f"El cliente {partner.name} no tiene NIT/CI configurado")

            cufd_record = self._obtener_cufd_valido_por_company(company)
            if not cufd_record:
                _logger.error("No se pudo obtener CUFD valido al generar XML")
                return None

            # Obtener numero de factura
            numero_factura = self._obtener_numero_factura()
            _logger.info(f"Numero de factura asignado: {numero_factura}")

            # IMPORTANTE: Generar fecha/hora UNA SOLA VEZ para usar en CUF y XML
            ahora_utc = datetime.now(timezone.utc)
            bolivia_tz = timezone(timedelta(hours=-4))
            ahora_bolivia = ahora_utc.astimezone(bolivia_tz)

            _logger.info(f"Fecha/Hora Bolivia (UTC-4): {ahora_bolivia}")

            # Generar CUF dinamicamente CON LA FECHA/HORA EXACTA
            _logger.info("Generando CUF dinamico con fecha/hora sincronizada...")
            cuf_resultado = self._generar_cuf_dinamico(numero_factura, ahora_bolivia)
            cuf_generado = cuf_resultado['cuf']

            _logger.info(f"CUF generado: {cuf_generado}")

            leyenda = self._obtener_leyenda_aleatoria()

            # Crear elemento raíz
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

            etree.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')

            cabecera = etree.SubElement(root, 'cabecera')

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

            # USAR LA MISMA FECHA/HORA que se usó para el CUF
            fecha_emision = ahora_bolivia.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            etree.SubElement(cabecera, 'fechaEmision').text = fecha_emision

            _logger.info(f"Fecha emision XML: {fecha_emision}")

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

            etree.SubElement(cabecera, 'codigoMetodoPago').text = '1'

            numero_tarjeta = etree.SubElement(cabecera, 'numeroTarjeta')
            numero_tarjeta.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            monto_total = round(self.amount_total, 2)
            etree.SubElement(cabecera, 'montoTotal').text = f"{monto_total:.2f}"
            etree.SubElement(cabecera, 'montoTotalSujetoIva').text = f"{monto_total:.2f}"
            etree.SubElement(cabecera, 'codigoMoneda').text = '1'
            etree.SubElement(cabecera, 'tipoCambio').text = '1'
            etree.SubElement(cabecera, 'montoTotalMoneda').text = f"{monto_total:.2f}"

            monto_gift_card = etree.SubElement(cabecera, 'montoGiftCard')
            monto_gift_card.text = '0'

            etree.SubElement(cabecera, 'descuentoAdicional').text = '0'

            codigo_excepcion = etree.SubElement(cabecera, 'codigoExcepcion')
            codigo_excepcion.text = '1'

            cafc = etree.SubElement(cabecera, 'cafc')
            cafc.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            etree.SubElement(cabecera, 'leyenda').text = leyenda[:200]
            etree.SubElement(cabecera, 'usuario').text = self.user_id.name[:100]
            etree.SubElement(cabecera, 'codigoDocumentoSector').text = '1'

            for line in self.lines:
                product = line.product_id
                product_tmpl = product.product_tmpl_id

                if not product_tmpl.siat_homologado:
                    _logger.warning(f"Producto {product.name} no homologado, saltando...")
                    continue

                detalle = etree.SubElement(root, 'detalle')

                etree.SubElement(detalle, 'actividadEconomica').text = str(product_tmpl.siat_codigo_actividad or '')[
                    :10]
                etree.SubElement(detalle, 'codigoProductoSin').text = str(product_tmpl.siat_codigo_producto or '0')
                etree.SubElement(detalle, 'codigoProducto').text = (product.default_code or f'PROD-{product.id}')[:50]
                etree.SubElement(detalle, 'descripcion').text = product.name[:500]
                etree.SubElement(detalle, 'cantidad').text = f"{line.qty:.2f}"
                etree.SubElement(detalle, 'unidadMedida').text = str(product_tmpl.siat_codigo_unidad_medida or 58)
                etree.SubElement(detalle, 'precioUnitario').text = f"{line.price_unit:.2f}"
                etree.SubElement(detalle, 'montoDescuento').text = f"{line.discount:.2f}" if line.discount else '0.00'

                subtotal = round(line.qty * line.price_unit, 2)
                etree.SubElement(detalle, 'subTotal').text = f"{subtotal:.2f}"

                serie = etree.SubElement(detalle, 'numeroSerie')
                serie.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

                imei = etree.SubElement(detalle, 'numeroImei')
                imei.set('{http://www.w3.org/2001/XMLSchema-instance}nil', 'true')

            xml_string = etree.tostring(
                root,
                pretty_print=True,
                xml_declaration=True,
                encoding='UTF-8',
                standalone=True
            ).decode('utf-8')

            xml_string = xml_string.replace(
                f'<{nombre_elemento_raiz} xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="{xsd_referencia}">',
                f'<{nombre_elemento_raiz} xsi:noNamespaceSchemaLocation="{xsd_referencia}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            )

            self.write({
                'siat_xml_factura': xml_string,
                'siat_cuf': cuf_generado,
                'siat_numero_factura': numero_factura
            })

            _logger.info("=" * 100)
            _logger.info("XML GENERADO EXITOSAMENTE")
            _logger.info("=" * 100)
            _logger.info(f"\n{xml_string}")
            _logger.info("=" * 100)
            _logger.info(f"CUF: {cuf_generado}")
            _logger.info(f"Numero Factura: {numero_factura}")
            _logger.info("=" * 100)

            # Firma digital para modalidad Electronica En Linea
            xml_a_enviar = xml_string
            if es_electronica:
                _logger.info("[POS] Modalidad Electronica - enviando al microservicio de firma...")
                config = self.company_id.siat_config_id
                if not config:
                    config = self.env['alpha.siat.config'].search([], limit=1)
                xml_firmado = self._firmar_xml_electronico(xml_string, config)
                self.write({'siat_xml_factura': xml_firmado})
                xml_a_enviar = xml_firmado
                _logger.info("✓ [POS] XML firmado y guardado")

            resultado_envio = self._enviar_factura_a_siat(xml_a_enviar, cufd_record)

            if resultado_envio and resultado_envio.get('success'):
                _logger.info("=" * 100)
                _logger.info("FACTURA EMITIDA EXITOSAMENTE")
                _logger.info(f"Estado: {resultado_envio.get('estado')} - {resultado_envio.get('descripcion')}")
                _logger.info(f"Codigo Recepcion: {resultado_envio.get('codigo_recepcion')}")
                _logger.info("=" * 100)
            return xml_string

        except Exception as e:
            _logger.error(f"Error generando XML: {str(e)}", exc_info=True)
            return None

    def _generar_cuf_dinamico(self, numero_factura, fecha_hora_bolivia):
        """Genera el CUF dinamicamente usando el generador de CUF"""
        self.ensure_one()

        try:
            cuf_generator = self.env['alpha.siat.cuf.generator']
            resultado = cuf_generator.generar_cuf(
                company_id=self.company_id.id,
                numero_factura=numero_factura,
                fecha_hora_emision=fecha_hora_bolivia  # NUEVO PARAMETRO
            )

            if resultado and resultado.get('cuf'):
                _logger.info(f"CUF generado exitosamente: {resultado['cuf']}")
                return resultado
            else:
                raise ValidationError("No se pudo generar el CUF")

        except Exception as e:
            _logger.error(f"Error generando CUF: {str(e)}", exc_info=True)
            raise ValidationError(f"Error al generar CUF: {str(e)}")

    def _enviar_factura_a_siat(self, xml_string, cufd_record):
        """Envía la factura generada a SIAT"""
        self.ensure_one()

        try:
            company = self.company_id

            # Buscar configuración SIAT
            config = company.siat_config_id

            # Si la compañía no tiene config asignada, buscar la primera disponible
            if not config:
                _logger.warning(
                    f"Compania {company.name} no tiene config SIAT asignada, buscando configuracion disponible...")
                config = self.env['alpha.siat.config'].search([], limit=1)

            if not config:
                error_msg = (
                    "NO HAY CONFIGURACION SIAT\n\n"
                    "No se encontro configuracion SIAT en el sistema.\n"
                    "Por favor:\n"
                    "1. Vaya a Facturacion > Configuracion > SIAT\n"
                    "2. Configure los parametros de conexion\n"
                    "3. Asigne la configuracion a la compania"
                )
                _logger.error(error_msg)
                raise ValidationError(error_msg)

            _logger.info(f"Usando configuracion SIAT: {config.name}")
            _logger.info(f"  Token: {'Configurado' if config.token else 'NO configurado'}")
            _logger.info(f"  Ambiente: {config.codigo_ambiente}")
            _logger.info(f"  Modalidad: {config.modalidad}")
            _logger.info(f"  Sistema: {config.codigo_sistema or 'NO configurado'}")
            _logger.info(f"  URL Codigos: {config.wsdl_codigos}")
            _logger.info(f"  URL Sync: {config.wsdl_sync_url}")
            _logger.info(f"  URL Facturacion: {config.wsdl_compra_venta}")

            # Validar que exista la URL de facturación
            if not config.wsdl_compra_venta:
                error_msg = (
                    "URL DE FACTURACION NO CONFIGURADA\n\n"
                    "El campo 'wsdl_compra_venta' no esta configurado.\n"
                    "Configure la URL del servicio de facturacion en SIAT Config."
                )
                _logger.error(error_msg)
                raise ValidationError(error_msg)

            # Obtener CUIS válido
            cuis_model = self.env['alpha.siat.cuis']
            try:
                cuis = cuis_model.get_or_fetch_cuis(company, codigo_modalidad=int(config.modalidad))
                _logger.info(f"CUIS obtenido: {cuis[:20]}...")
            except Exception as e:
                error_msg = (
                    f"ERROR OBTENIENDO CUIS\n\n"
                    f"No se pudo obtener el codigo CUIS de SIAT.\n"
                    f"Error: {str(e)}\n\n"
                    f"Verifique:\n"
                    f"1. Que la configuracion SIAT sea correcta\n"
                    f"2. Que tenga conexion a internet\n"
                    f"3. Que el token de SIAT sea valido"
                )
                _logger.error(error_msg)
                raise ValidationError(error_msg)

            # Enviar factura
            _logger.info("Iniciando envio de factura a SIAT...")
            client = self.env['alpha.siat.client'].sudo()
            resultado = client.enviar_factura_siat(
                company=company,
                config=config,
                cuis=cuis,
                cufd=cufd_record.cufd,
                xml_string=xml_string
            )

            # Verificar si hubo error en el envío
            if resultado.get('error'):
                estado = resultado.get('estado', 'ERROR')
                mensajes = resultado.get('mensajes', 'Error desconocido')

                error_msg = (
                    f"FACTURA RECHAZADA POR SIAT\n\n"
                    f"Estado: {estado}\n"
                    f"Mensaje: {mensajes}\n\n"
                    f"La factura no puede ser emitida sin confirmacion de SIAT."
                )
                _logger.error(error_msg)

                self.write({
                    'siat_estado_envio': estado,
                    'siat_mensajes_envio': mensajes,
                    'siat_fecha_envio': fields.Datetime.now()
                })
                raise ValidationError(error_msg)

            # Si el envío fue exitoso, guardar resultado
            datos_siat = {
                'siat_estado_envio': resultado.get('estado', ''),
                'siat_codigo_recepcion': resultado.get('codigoRecepcion', ''),
                'siat_mensajes_envio': resultado.get('mensajes', ''),
                'siat_fecha_envio': fields.Datetime.now()
            }

            self.write(datos_siat)
            if self.account_move:
                _logger.info(f"Sincronizando datos SIAT con factura {self.account_move.name}...")

                # Copiar TODOS los datos SIAT a la factura
                self.account_move.write({
                    'siat_xml_factura': self.siat_xml_factura,
                    'siat_cuf': self.siat_cuf,
                    'siat_numero_factura': self.siat_numero_factura,
                    'siat_estado_envio': datos_siat['siat_estado_envio'],
                    'siat_codigo_recepcion': datos_siat['siat_codigo_recepcion'],
                    'siat_mensajes_envio': datos_siat['siat_mensajes_envio'],
                    'siat_fecha_envio': datos_siat['siat_fecha_envio'],
                })

                _logger.info(f"✓ Datos SIAT sincronizados con factura {self.account_move.name}")
                _logger.info(f"  - CUF: {self.siat_cuf}")
                _logger.info(f"  - Estado: {datos_siat['siat_estado_envio']}")
                _logger.info(f"  - Código Recepción: {datos_siat['siat_codigo_recepcion']}")
            else:
                _logger.warning("⚠ Orden POS no tiene factura asociada (account_move)")

            estado = resultado.get('estado', '')
            descripcion = resultado.get('descripcion_estado', '')
            codigo_recepcion = resultado.get('codigoRecepcion', '')

            _logger.info("=" * 100)
            _logger.info("FACTURA ACEPTADA POR SIAT")
            _logger.info(f"  Estado: {resultado.get('estado')}")
            _logger.info(f"  Codigo Recepcion: {resultado.get('codigoRecepcion')}")
            _logger.info(f"  Descripcion: {resultado.get('descripcion_estado', '')}")
            _logger.info("=" * 100)

            return {
                'success': True,
                'estado': estado,
                'descripcion': descripcion,
                'codigo_recepcion': codigo_recepcion
            }

        except ValidationError:
            raise
        except Exception as e:
            error_msg = (
                f"ERROR CRITICO\n\n"
                f"Ocurrio un error inesperado al enviar la factura:\n"
                f"{str(e)}\n\n"
                f"La factura no puede ser emitida."
            )
            _logger.error(error_msg, exc_info=True)
            raise ValidationError(error_msg)

    def _obtener_leyenda_aleatoria(self):
        """Obtiene una leyenda aleatoria del catalogo SIAT"""
        leyendas = self.env['alpha.siat.leyenda'].search([
            ('company_id', '=', self.company_id.id)
        ])

        if leyendas:
            leyenda = random.choice(leyendas)
            return leyenda.descripcion_leyenda
        else:
            return "Ley N 453: El proveedor debe brindar atencion sin discriminacion, con respeto, calidez y cordialidad a los usuarios y consumidores."

    def _get_receipt_data_siat(self):
        """Prepara los datos SIAT para el receipt"""
        self.ensure_one()

        # Si no es factura o no tiene CUF, retornar None
        if not self.to_invoice or not self.siat_cuf:
            _logger.info(f"[RECEIPT] Orden {self.name} - No tiene factura SIAT")
            return None

        company = self.company_id

        qr_base_url = self._get_siat_qr_base_url()

        qr_data = {
            'nit': company.vat or '',
            'cuf': self.siat_cuf or '',
            'numero': self.siat_numero_factura or 0,
            't': 1
        }

        siat_qr_url = f"{qr_base_url}nit={qr_data['nit']}&cuf={qr_data['cuf']}&numero={qr_data['numero']}&t={qr_data['t']}"

        _logger.info("=" * 100)
        _logger.info("[RECEIPT] PREPARANDO DATOS SIAT PARA EL RECEIPT")
        _logger.info(f"  URL Base QR: {qr_base_url}")
        _logger.info(f"  NIT Emisor: {company.vat}")
        _logger.info(f"  CUF: {self.siat_cuf}")
        _logger.info(f"  Número Factura: {self.siat_numero_factura}")
        _logger.info(f"  URL QR: {siat_qr_url}")
        _logger.info("=" * 100)

        result = {
            'siat_enabled': True,
            'siat_qr_url': siat_qr_url,
            'siat_cuf': self.siat_cuf,
            'siat_numero_factura': self.siat_numero_factura,
            'siat_codigo_recepcion': self.siat_codigo_recepcion or '',
            'siat_fecha_emision': self.siat_fecha_envio.strftime('%d/%m/%Y %H:%M:%S') if self.siat_fecha_envio else '',
            'siat_estado': self.siat_estado_envio or '',
            'empresa_nit': company.vat or '',
            'empresa_razon_social': company.name or '',
            'cliente_nit': self.partner_id.vat or '',
            'cliente_razon_social': self.partner_id.name or '',
        }

        return result

    @api.model
    def _order_fields(self, ui_order):
        """
        Override para incluir campos SIAT cuando se sincroniza la orden
        Este método se llama cuando el POS envía la orden al backend
        """
        _logger.info("[ORDER_FIELDS] Procesando campos de orden desde UI")
        fields = super()._order_fields(ui_order)

        return fields

    def _export_for_ui(self, order):
        """
        Override para agregar datos SIAT al receipt
        Este método se llama cuando se obtiene la orden para mostrar en UI
        """
        _logger.info(f"[EXPORT_FOR_UI] Exportando orden {order.name} para UI")

        # Llamar al método padre para obtener los datos base
        result = super()._export_for_ui(order)

        _logger.info(f"[EXPORT_FOR_UI] Orden {order.name} - to_invoice: {order.to_invoice}")
        _logger.info(f"[EXPORT_FOR_UI] Orden {order.name} - siat_cuf: {order.siat_cuf}")

        # Agregar datos SIAT si la orden está facturada
        if order.to_invoice and order.siat_cuf:
            siat_data = order._get_receipt_data_siat()
            if siat_data:
                result['siat_data'] = siat_data
                _logger.info(f"[EXPORT_FOR_UI] ✓ Datos SIAT agregados a la orden {order.name}")
                _logger.info(f"[EXPORT_FOR_UI] SIAT Data: {siat_data}")
            else:
                _logger.warning(f"[EXPORT_FOR_UI] ⚠ No se pudieron obtener datos SIAT para orden {order.name}")
        else:
            _logger.info(f"[EXPORT_FOR_UI] Orden {order.name} sin factura SIAT")

        return result