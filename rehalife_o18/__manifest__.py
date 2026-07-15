# -*- coding: utf-8 -*-
{
    'name': 'Rehalife',
    'version': '18.0.1.0.0',
    'summary': 'Modulo de gestion ',
    'description': """
        Modulo de integracion con el backend de Rehalife
    """,
    'author': 'Alpha systems',
    'website': 'https://rehalife.com',
    'depends': ['base','account', 'mail', 'contacts', 'partner_autocomplete', 'point_of_sale', 'alpha_siat'],
    'post_init_hook': 'post_init_hook',
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/res_config_settings_views.xml',
        'views/rehalife_city_views.xml',
        'views/rehalife_partner_views.xml',
        'views/rehalife_reservation_views.xml',
        'wizards/rehalife_sync_wizard_view.xml',
        'wizards/rehalife_import_reservations_wizard_view.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'rehalife_o18/static/src/xml/reservation_screen.xml',
            'rehalife_o18/static/src/js/reservation_button.js',
        ],
    },
    'installable': True,
    'application': False,
}
