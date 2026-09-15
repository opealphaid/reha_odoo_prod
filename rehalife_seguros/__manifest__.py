# -*- coding: utf-8 -*-
{
    'name': 'Rehalife Seguros',
    'version': '18.0.1.0.0',
    'summary': 'Gestion de atenciones cubiertas por aseguradoras (Notas de Conformidad, Pedidos de Venta Marco)',
    'description': """
        Modulo de gestion de aseguradoras para Rehalife:
        - Pedidos de Venta Marco por aseguradora/periodo
        - Notas de Conformidad (certificado clinico + soporte administrativo)
        - Facturacion agrupada hacia aseguradoras
    """,
    'author': 'Alpha systems',
    'website': 'https://rehalife.com',
    'depends': ['base', 'sale', 'account', 'alpha_siat', 'rehalife_o18'],
    'data': [
        'security/rehalife_seguros_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/rehalife_seguros_res_partner_views.xml',
        'report/rehalife_seguros_pedido_marco_report.xml',
        'views/rehalife_seguros_sale_order_views.xml',
        'views/rehalife_seguros_account_move_views.xml',
        'views/rehalife_seguros_reservation_views.xml',
        'report/rehalife_seguros_nota_conformidad_report.xml',
        'views/rehalife_seguros_nota_conformidad_views.xml',
        'views/rehalife_seguros_config_views.xml',
        'report/rehalife_seguros_reporte_nc_report.xml',
        'wizards/rehalife_seguros_reporte_nc_wizard_view.xml',
        'views/rehalife_seguros_menu_views.xml',
    ],
    'installable': True,
    'application': False,
}
