# -*- coding: utf-8 -*-
{
    'name': 'POS Custom Receipt - Reha',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Personalización del recibo POS con QR',
    'author': 'Alpha Systems S.R.L.',
    'depends': ['point_of_sale', 'alpha_siat'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/ganadero_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'custom_receipt/static/src/xml/receipt.xml',
            'custom_receipt/static/src/js/receipt.js',
            'custom_receipt/static/src/css/receipt_print.css',

            'custom_receipt/static/src/popups/image_popup.js',
            'custom_receipt/static/src/popups/qr_payment_popup.js',
            'custom_receipt/static/src/overrides/payment_screen.js',
            # Después los XML
            'custom_receipt/static/src/popups/image_popup.xml',
            'custom_receipt/static/src/popups/qr_payment_popup.xml',
            'custom_receipt/static/src/overrides/payment_screen.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}