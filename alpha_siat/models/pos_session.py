import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _pos_ui_models_to_load(self):
        """
        Asegurar que los campos SIAT se carguen en el POS
        """
        result = super()._pos_ui_models_to_load()
        return result

    def _loader_params_pos_order(self):
        """
        Agregar campos SIAT a los parámetros de carga de órdenes
        """
        result = super()._loader_params_pos_order()

        # Agregar campos SIAT a los campos que se cargan
        if 'search_params' in result and 'fields' in result['search_params']:
            result['search_params']['fields'].extend([
                'siat_xml_factura',
                'siat_cuf',
                'siat_numero_factura',
                'siat_estado_envio',
                'siat_codigo_recepcion',
                'siat_mensajes_envio',
                'siat_fecha_envio',
            ])

            _logger.info("[POS_SESSION] Campos SIAT agregados a loader_params")

        return result

    def _get_pos_ui_pos_order(self, params):
        """
        Modificar las órdenes que se envían al UI para incluir datos SIAT
        """
        _logger.info("[GET_POS_UI] Obteniendo órdenes para UI")

        # Obtener órdenes del método padre
        orders = super()._get_pos_ui_pos_order(params)

        # Agregar datos SIAT a cada orden
        for order_data in orders:
            order_id = order_data.get('id')
            if order_id:
                order = self.env['pos.order'].browse(order_id)

                if order.to_invoice and order.siat_cuf:
                    siat_data = order._get_receipt_data_siat()
                    if siat_data:
                        order_data['siat_data'] = siat_data
                        _logger.info(f"[GET_POS_UI] ✓ Datos SIAT agregados a orden {order.name}")

        return orders