# alpha_siat/models/siat_config.py
from odoo import models, fields


class SiatConfig(models.Model):
    _name = "alpha.siat.config"
    _description = "SIAT Configuration"
    _rec_name = "name"

    name = fields.Char(default="SIAT Configuration", required=True)

    wsdl_sync_url = fields.Char(
        string="WSDL - Servicio Sincronización",
        required=True,
        default="https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"
    )
    wsdl_codigos = fields.Char(
        string="WSDL - Servicio Codigos",
        required=True,
        default="https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
    )
    wsdl_compra_venta = fields.Char(
        string="WSDL - Servicios de Compra y Venta",
        required=True,
        default="https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"
    )

    url_qr = fields.Selection([
        ('https://pilotosiat.impuestos.gob.bo/consulta/QR?', 'Piloto SIAT (Pruebas)'),
        ('https://siat.impuestos.gob.bo/consulta/QR?', 'SIAT Producción')
    ], string="URL QR SIAT", required=True, default='https://pilotosiat.impuestos.gob.bo/consulta/QR?',
        help="URL base para generar códigos QR de facturación")

    token = fields.Char(string="SIAT Token", required=False, help="Token used to authenticate requests to SIAT")
    codigo_ambiente = fields.Selection([('1', 'Producción'), ('2', 'Pruebas')], required=True, default='2')
    codigo_sistema = fields.Char(string="Código Sistema (SIAT)", required=False)
    modalidad = fields.Selection([('1', 'Electrónica En Línea'), ('2', 'Computarizada En Línea')], string="Modalidad",
                                 required=True, default='1')

    url_firma = fields.Char(
        string="URL Microservicio de Firma",
        help="Endpoint del microservicio externo que firma el XML para factura electronica. "
             "Ej: http://190.181.63.219:8080/api/firma/firmar"
    )