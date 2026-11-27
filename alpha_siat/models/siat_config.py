# alpha_siat/models/siat_config.py
import logging

from odoo import api, models, fields

_logger = logging.getLogger(__name__)

# ── URL del QR de consulta de facturas SIAT ─────────────────────────────────
# Fuente oficial (Impuestos Nacionales, "Código de Respuesta Rápida (QR)"):
# https://siatinfo.impuestos.gob.bo/index.php/facturacion-en-linea/algoritmos-utilizados/codigo-respuesta-rapida-qr
# Formato: <base>nit=<NIT emisor>&cuf=<CUF>&numero=<N° factura>&t=<tamaño>
# - La BASE depende del ambiente (codigo_ambiente): Pruebas → pilotosiat,
#   Producción → siat.
# - t NO depende del ambiente: es el tamaño de la pre-visualización de la
#   factura en la página del SIAT ("t=valorTamaño": 1 = rollo, 2 = media
#   hoja; si se omite vale 1).
SIAT_QR_BASE_URLS = {
    '1': 'https://siat.impuestos.gob.bo/consulta/QR?',        # Producción
    '2': 'https://pilotosiat.impuestos.gob.bo/consulta/QR?',  # Pruebas
}
SIAT_QR_AMBIENTE_DEFAULT = '2'
SIAT_QR_TAMANOS = {
    'rollo': 1,       # ticket del POS
    'media_hoja': 2,  # PDF de account.move
}
SIAT_QR_TAMANO_DEFAULT = 1


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
    ], string="URL QR SIAT (sin uso)", default='https://pilotosiat.impuestos.gob.bo/consulta/QR?',
        help="YA NO SE USA. La URL del QR la decide Código Ambiente "
             "(Pruebas → pilotosiat, Producción → siat). Se conserva solo "
             "para no perder el dato existente.")

    token = fields.Char(string="SIAT Token", required=False, help="Token used to authenticate requests to SIAT")
    codigo_ambiente = fields.Selection(
        [('1', 'Producción'), ('2', 'Pruebas')], required=True, default='2',
        help="Ambiente que se envía al SIAT en cada solicitud. También define "
             "la URL del QR impreso en las facturas (ticket del POS y PDF): "
             "Pruebas → pilotosiat.impuestos.gob.bo, Producción → "
             "siat.impuestos.gob.bo.")
    codigo_sistema = fields.Char(string="Código Sistema (SIAT)", required=False)
    modalidad = fields.Selection([('1', 'Electrónica En Línea'), ('2', 'Computarizada En Línea')], string="Modalidad",
                                 required=True, default='1')

    url_firma = fields.Char(
        string="URL Microservicio de Firma",
        help="Endpoint del microservicio externo que firma el XML para factura electronica. "
             "Ej: http://190.181.63.219:8080/api/firma/firmar"
    )

    @api.model
    def _get_config_for_company(self, company):
        """Config SIAT de la compañía: company.siat_config_id o, si no tiene,
        el primer registro (mismo patrón que el resto de alpha_siat).

        Usa el entorno de self (llamar con .sudo() para que lo puedan usar
        el cajero del POS o un contable: el ACL de alpha.siat.config es solo
        de base.group_system)."""
        company = company.with_env(self.env) if company else company
        return (company and company.siat_config_id) or self.search([], limit=1)

    def get_siat_qr_url(self, nit, cuf, numero, formato='rollo'):
        """URL completa del QR de consulta SIAT.

        Se llama sobre UN registro de config (el ambiente sale de
        codigo_ambiente). Sin config (recordset vacío) usa Pruebas y deja un
        warning. formato: 'rollo' (t=1) o 'media_hoja' (t=2); uno
        desconocido usa t=1 con warning. Ver la fuente oficial junto a
        SIAT_QR_BASE_URLS."""
        if self:
            self.ensure_one()
            ambiente = self.codigo_ambiente
        else:
            _logger.warning(
                "[SIAT QR] No hay configuración SIAT; se arma la URL del QR "
                "con el ambiente de Pruebas.")
            ambiente = SIAT_QR_AMBIENTE_DEFAULT
        base = SIAT_QR_BASE_URLS.get(ambiente)
        if not base:
            _logger.warning(
                "[SIAT QR] codigo_ambiente desconocido %r; se usa Pruebas.", ambiente)
            base = SIAT_QR_BASE_URLS[SIAT_QR_AMBIENTE_DEFAULT]
        tamano = SIAT_QR_TAMANOS.get(formato)
        if tamano is None:
            _logger.warning(
                "[SIAT QR] Formato de QR desconocido %r; se usa t=%s (rollo).",
                formato, SIAT_QR_TAMANO_DEFAULT)
            tamano = SIAT_QR_TAMANO_DEFAULT
        numero = '' if numero is None or numero is False else numero
        return f"{base}nit={nit or ''}&cuf={cuf or ''}&numero={numero}&t={tamano}"
